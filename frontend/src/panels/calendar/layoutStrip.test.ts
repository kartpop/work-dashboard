import { describe, expect, it } from "vitest";
import { layoutBlocks, type StripEvent } from "./layoutStrip";

// 9a–6p default window, in minutes from midnight.
const W_START = 9 * 60;
const W_END = 18 * 60;

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
    // 10:00–11:00 in a 9–18 (540 min) window.
    const { blocks } = layoutBlocks([ev("a", 600, 660)], W_START, W_END);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].leftPct).toBeCloseTo(((600 - 540) / 540) * 100); // ~11.11
    expect(blocks[0].widthPct).toBeCloseTo((60 / 540) * 100); // ~11.11
    expect(blocks[0].lane).toBe(0);
  });

  it("stacks two overlapping events into two lanes", () => {
    const { blocks } = layoutBlocks(
      [ev("a", 600, 720), ev("b", 660, 780)],
      W_START,
      W_END,
    );
    const byId = Object.fromEntries(blocks.map((b) => [b.id, b]));
    expect(byId.a.lane).toBe(0);
    expect(byId.b.lane).toBe(1);
  });

  it("keeps non-overlapping events in the same lane", () => {
    const { blocks } = layoutBlocks(
      [ev("a", 600, 660), ev("b", 700, 760)],
      W_START,
      W_END,
    );
    expect(blocks.every((b) => b.lane === 0)).toBe(true);
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
    // 8:30–9:30 → clipped to start at 9:00.
    const { blocks } = layoutBlocks([ev("a", 510, 570)], W_START, W_END);
    expect(blocks[0].leftPct).toBe(0);
    expect(blocks[0].widthPct).toBeCloseTo((30 / 540) * 100);
  });

  it("counts events outside the window for the chevron hint", () => {
    const { blocks, beforeCount, afterCount } = layoutBlocks(
      [ev("early", 450, 480), ev("mid", 600, 660), ev("late", 1140, 1200)],
      W_START,
      W_END,
    );
    expect(blocks.map((b) => b.id)).toEqual(["mid"]);
    expect(beforeCount).toBe(1);
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
