import { describe, expect, it } from "vitest";
import { layoutBlocks, type StripEvent } from "./layoutStrip";

// 8a–7p default window, in minutes from midnight.
const W_START = 8 * 60;
const W_END = 19 * 60;
const SPAN = W_END - W_START;

function ev(
  id: string,
  startMin: number,
  endMin: number,
  extra: Partial<StripEvent> = {},
): StripEvent {
  return { id, title: id, startMin, endMin, ...extra };
}

describe("layoutBlocks", () => {
  it("positions a block proportionally within the window", () => {
    // 10:00–11:00 in an 8–19 (660 min) window.
    const { blocks } = layoutBlocks([ev("a", 600, 660)], W_START, W_END);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].leftPct).toBeCloseTo(((600 - W_START) / SPAN) * 100);
    expect(blocks[0].widthPct).toBeCloseTo((60 / SPAN) * 100);
    expect(blocks[0].clusterIds).toEqual(["a"]);
    expect(blocks[0].extraCount).toBe(0);
    expect(blocks[0].stackIndex).toBe(0);
  });

  it("stacks the shorter meeting in front of a longer one, even when the long one is accepted", () => {
    // A 30-min accepted meeting inside a 4-hour focus block must stay visible.
    const { blocks } = layoutBlocks(
      [ev("focus", 600, 840), ev("standup", 660, 690)],
      W_START,
      W_END,
    );
    const byId = Object.fromEntries(blocks.map((b) => [b.id, b]));
    expect(byId.standup.zIndex).toBeGreaterThan(byId.focus.zIndex);
    expect(byId.standup.stackIndex).toBe(1);
    expect(byId.focus.stackIndex).toBe(0);
    // The front block carries the +N badge.
    expect(byId.standup.extraCount).toBe(1);
    expect(byId.focus.extraCount).toBe(0);
  });

  it("puts the accepted event in front when durations tie", () => {
    const { blocks } = layoutBlocks(
      [ev("gray", 600, 720, { accepted: false }), ev("orange", 660, 780)],
      W_START,
      W_END,
    );
    const byId = Object.fromEntries(blocks.map((b) => [b.id, b]));
    expect(byId.gray.clusterIds).toEqual(["gray", "orange"]);
    expect(byId.orange.clusterIds).toEqual(["gray", "orange"]);
    expect(byId.orange.zIndex).toBeGreaterThan(byId.gray.zIndex);
    expect(byId.orange.extraCount).toBe(1);
    expect(byId.gray.extraCount).toBe(0);
  });

  it("assigns every cluster member a distinct stack level", () => {
    const { blocks } = layoutBlocks(
      [
        ev("long", 600, 780),
        ev("mid", 630, 720, { accepted: false }),
        ev("short", 660, 690),
      ],
      W_START,
      W_END,
    );
    const byId = Object.fromEntries(blocks.map((b) => [b.id, b]));
    expect(byId.long.stackIndex).toBe(0);
    expect(byId.mid.stackIndex).toBe(1);
    expect(byId.short.stackIndex).toBe(2);
    expect(byId.short.extraCount).toBe(2);
  });

  it("chains transitive overlaps into one cluster", () => {
    // a–b overlap, b–c overlap, a–c don't: all three share one cluster.
    const { blocks } = layoutBlocks(
      [ev("a", 600, 700), ev("b", 650, 750), ev("c", 740, 800)],
      W_START,
      W_END,
    );
    const byId = Object.fromEntries(blocks.map((b) => [b.id, b]));
    expect(byId.a.clusterIds).toEqual(["a", "b", "c"]);
    // The front block (shortest — c) carries the +N badge.
    expect(byId.c.extraCount).toBe(2);
    expect(byId.a.extraCount).toBe(0);
  });

  it("keeps non-overlapping events in separate clusters", () => {
    const { blocks } = layoutBlocks(
      [ev("a", 600, 660), ev("b", 700, 760)],
      W_START,
      W_END,
    );
    const byId = Object.fromEntries(blocks.map((b) => [b.id, b]));
    expect(byId.a.clusterIds).toEqual(["a"]);
    expect(byId.b.clusterIds).toEqual(["b"]);
    expect(blocks.every((b) => b.extraCount === 0)).toBe(true);
  });

  it("excludes all-day events (no blocks)", () => {
    const { blocks } = layoutBlocks(
      [ev("holiday", W_START, W_END, { allDay: true })],
      W_START,
      W_END,
    );
    expect(blocks).toHaveLength(0);
  });

  it("clips events straddling the window edges", () => {
    // 7:30–8:30 → clipped to start at 8:00.
    const { blocks } = layoutBlocks([ev("a", 450, 510)], W_START, W_END);
    expect(blocks[0].leftPct).toBe(0);
    expect(blocks[0].widthPct).toBeCloseTo((30 / SPAN) * 100);
  });

  it("counts events outside the window for the chevron badges", () => {
    const { blocks, beforeCount, afterCount } = layoutBlocks(
      [
        ev("early", 400, 450),
        ev("early2", 420, 470),
        ev("mid", 600, 660),
        ev("late", 1150, 1200),
      ],
      W_START,
      W_END,
    );
    expect(blocks.map((b) => b.id)).toEqual(["mid"]);
    expect(beforeCount).toBe(2);
    expect(afterCount).toBe(1);
  });

  it("enforces a minimum clickable width for tiny meetings", () => {
    const { blocks } = layoutBlocks([ev("a", 600, 601)], W_START, W_END);
    expect(blocks[0].widthPct).toBeGreaterThanOrEqual(1.5);
  });

  it("returns nothing for a zero/negative window", () => {
    expect(layoutBlocks([ev("a", 600, 660)], 600, 600).blocks).toHaveLength(0);
  });
});
