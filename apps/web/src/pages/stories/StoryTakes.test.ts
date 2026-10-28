/** CO-7: what the takes timeline says about the change from the first take to the last. */
import { describe, expect, it } from "vitest";

import type { TakeOut } from "../coach/api";
import { bestTake, takesTrend } from "./StoryTakes";

function take(id: string, scores: number[], durationS: number | null = null): TakeOut {
  return {
    id,
    story_id: "s1",
    channel: durationS === null ? "text" : "voice",
    text: "A telling.",
    duration_s: durationS,
    status: "scored",
    scores: scores.map((score) => ({ competency: "ownership", score, justification: "j", quotes: [] })),
    reason: null,
    created_at: "2026-10-20T10:00:00Z",
  } as TakeOut;
}

describe("takes trend", () => {
  it("CO-7: says shorter and stronger each time only when every take beat the one before", () => {
    expect(takesTrend([take("a", [2], 160), take("b", [3], 130), take("c", [4], 112)])).toBe(
      "2:40 → 1:52. Shorter and stronger each time.",
    );
    expect(takesTrend([take("a", [2], 160), take("b", [3], 170), take("c", [4], 112)])).toBe(
      "2:40 → 1:52. Stronger each time.",
    );
  });

  it("CO-7: otherwise compares the last take with the first, and says nothing for one take", () => {
    expect(takesTrend([take("a", [2]), take("b", [1]), take("c", [3])])).toBe("Stronger than your first take.");
    expect(takesTrend([take("a", [3]), take("b", [2])])).toBe("Not as strong as your first take yet. Try the coach notes.");
    expect(takesTrend([take("a", [3]), take("b", [3])])).toBe("About as strong as your first take.");
    expect(takesTrend([take("a", [3])])).toBeNull();
  });

  it("CO-7: the best take is the highest average, the later one on a tie", () => {
    expect(bestTake([take("a", [3, 4]), take("b", [2]), take("c", [4, 3])])?.id).toBe("c");
    expect(bestTake([])).toBeNull();
  });
});
