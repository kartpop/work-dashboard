/**
 * Pure layout math for the calendar header strip (goal 7b) — the strip's analog
 * of `bulletEditor.ts`. Given events expressed as minutes-from-IST-midnight and a
 * visible window, it produces proportional left/width percentages and a ≤2-lane
 * assignment for overlaps. No DOM, no clock, no fetch — unit-tested in isolation.
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
}

export interface PositionedBlock {
  id: string;
  title: string | null;
  /** Percentages within the visible window (0–100). */
  leftPct: number;
  widthPct: number;
  /** 0 or 1 — at most two lanes; overflow past two stacks into lane 1. */
  lane: number;
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

  // Assign lanes greedily by start time: lane 0 unless it overlaps lane 0's last
  // block, then lane 1; a third concurrent block overflows into lane 1 too.
  const sorted = [...visible].sort(
    (a, b) => a.startMin - b.startMin || a.endMin - b.endMin,
  );
  const laneEnds: number[] = [-Infinity, -Infinity]; // clipped end-min per lane

  const blocks: PositionedBlock[] = sorted.map((e) => {
    const clippedStart = Math.max(e.startMin, windowStartMin);
    const clippedEnd = Math.min(e.endMin, windowEndMin);

    let lane = 0;
    if (clippedStart < laneEnds[0]) lane = 1;
    laneEnds[lane] = clippedEnd;

    const leftPct = ((clippedStart - windowStartMin) / span) * 100;
    const rawWidth = ((clippedEnd - clippedStart) / span) * 100;
    const widthPct = Math.min(100 - leftPct, Math.max(MIN_WIDTH_PCT, rawWidth));

    return { id: e.id, title: e.title, leftPct, widthPct, lane };
  });

  return { blocks, beforeCount, afterCount };
}
