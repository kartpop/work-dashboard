/**
 * Pure layout math for the calendar header strip (goal 7b) — the strip's analog
 * of `bulletEditor.ts`. Given events expressed as minutes-from-IST-midnight and a
 * visible window, it produces proportional left/width percentages and groups
 * overlapping events into clusters. No DOM, no clock, no fetch — unit-tested in
 * isolation.
 *
 * Overlap model (daily-driver feedback): blocks share one lane and physically
 * stack, back-to-front by duration — longest behind, shortest in front — so a
 * 30-min meeting inside a 4-hour focus block stays visible and clickable. Equal
 * durations put the owner-accepted event in front. The component staggers each
 * stacked block down a few pixels (`stackIndex`) so every event keeps a visible
 * sliver: nothing is ever fully eclipsed. The front block carries an
 * `extraCount` badge (+N); clicking any block of a multi-event cluster opens a
 * picker over `clusterIds`.
 *
 * The ISO → IST-minutes conversion lives in the hook/component (it needs a real
 * clock/timezone); this function only does geometry so it stays deterministic.
 */

export interface StripEvent {
  id: string;
  title: string | null;
  /** Minutes from IST midnight (0–1440). */
  startMin: number;
  endMin: number;
  allDay?: boolean;
  /** Owner's RSVP; undefined/true = accepted (own solo events have no RSVP). */
  accepted?: boolean;
}

export interface PositionedBlock {
  id: string;
  title: string | null;
  /** Percentages within the visible window (0–100). */
  leftPct: number;
  widthPct: number;
  accepted: boolean;
  /** Position in the cluster's back-to-front stack: 0 = backmost (longest).
   * The component offsets each level down a few px so slivers stay visible. */
  stackIndex: number;
  /** Stacking order (front = higher). Clusters never overlap, so values repeat. */
  zIndex: number;
  /** Every event id in this block's overlap cluster (incl. self), start order. */
  clusterIds: string[];
  /** On the cluster's front block only: how many others share its slot. */
  extraCount: number;
}

export interface StripLayout {
  blocks: PositionedBlock[];
  /** Timed events that end at/before the window start (reachable via ← chevron). */
  beforeCount: number;
  /** Timed events that start at/after the window end (reachable via → chevron). */
  afterCount: number;
}

const MIN_WIDTH_PCT = 1.5; // keep a 5-minute meeting clickable

/**
 * Lay out `events` inside `[windowStartMin, windowEndMin]`. All-day events are
 * excluded (they'd span the whole axis — MVP). Events fully outside the window
 * are dropped from `blocks` but counted for the out-of-window hint. Events that
 * straddle an edge are clipped to the window.
 */
export function layoutBlocks(
  events: StripEvent[],
  windowStartMin: number,
  windowEndMin: number,
): StripLayout {
  const span = windowEndMin - windowStartMin;
  if (span <= 0) return { blocks: [], beforeCount: 0, afterCount: 0 };

  const timed = events.filter((e) => !e.allDay && e.endMin > e.startMin);

  let beforeCount = 0;
  let afterCount = 0;
  const visible = timed.filter((e) => {
    if (e.endMin <= windowStartMin) {
      beforeCount += 1;
      return false;
    }
    if (e.startMin >= windowEndMin) {
      afterCount += 1;
      return false;
    }
    return true;
  });

  const sorted = [...visible].sort(
    (a, b) => a.startMin - b.startMin || a.endMin - b.endMin,
  );

  // Chain overlapping events into clusters over their clipped ranges: an event
  // joins the open cluster while it starts before the cluster's max end.
  const clusters: StripEvent[][] = [];
  let clusterEnd = -Infinity;
  for (const e of sorted) {
    const clippedStart = Math.max(e.startMin, windowStartMin);
    const clippedEnd = Math.min(e.endMin, windowEndMin);
    if (clusters.length > 0 && clippedStart < clusterEnd) {
      clusters[clusters.length - 1].push(e);
      clusterEnd = Math.max(clusterEnd, clippedEnd);
    } else {
      clusters.push([e]);
      clusterEnd = clippedEnd;
    }
  }

  const blocks: PositionedBlock[] = [];
  for (const cluster of clusters) {
    const clusterIds = cluster.map((e) => e.id);

    // Back-to-front: longest first (backmost) so short meetings surface; equal
    // durations put the accepted one in front; then later start in front.
    const stacked = [...cluster].sort((a, b) => {
      const durA = a.endMin - a.startMin;
      const durB = b.endMin - b.startMin;
      if (durA !== durB) return durB - durA;
      const accA = a.accepted !== false ? 1 : 0;
      const accB = b.accepted !== false ? 1 : 0;
      if (accA !== accB) return accA - accB;
      return a.startMin - b.startMin;
    });

    stacked.forEach((e, stackIndex) => {
      const clippedStart = Math.max(e.startMin, windowStartMin);
      const clippedEnd = Math.min(e.endMin, windowEndMin);
      const leftPct = ((clippedStart - windowStartMin) / span) * 100;
      const rawWidth = ((clippedEnd - clippedStart) / span) * 100;
      const widthPct = Math.min(
        100 - leftPct,
        Math.max(MIN_WIDTH_PCT, rawWidth),
      );

      const isFront = stackIndex === stacked.length - 1;

      blocks.push({
        id: e.id,
        title: e.title,
        leftPct,
        widthPct,
        accepted: e.accepted !== false,
        stackIndex,
        zIndex: 1 + stackIndex,
        clusterIds,
        extraCount: isFront ? cluster.length - 1 : 0,
      });
    });
  }

  return { blocks, beforeCount, afterCount };
}
