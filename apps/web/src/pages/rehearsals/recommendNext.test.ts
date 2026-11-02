/** RMAP-1: the recommended take inside a filter follows the API's rule (RH-4). */
import { describe, expect, it } from "vitest";

import type { RehearsalItem } from "../../api/types";
import { recommendNext } from "./RehearsalsPage";

const item = (id: string, score: number | null, date: string | null, created = "2026-10-01T10:00:00Z") =>
  ({
    interview: { id, created_at: created },
    readiness: { score },
    role: { id: "r", interview_date: date },
  }) as unknown as RehearsalItem;

describe("recommendNext", () => {
  it("RMAP-1: the closest interview date first, then the lowest readiness, below the goal only", () => {
    expect(recommendNext([item("a", 40, null), item("b", 60, "2026-11-20"), item("c", 50, "2026-11-10")])?.interview.id).toBe("c");
    expect(recommendNext([item("a", 40, null), item("b", null, null)])?.interview.id).toBe("b");
    expect(recommendNext([item("a", 80, "2026-11-10"), item("b", 70, null)])?.interview.id).toBe("b");
  });

  it("RMAP-1: the oldest interview breaks a tie, and nothing is recommended when all are at the goal", () => {
    const tie = [item("new", 50, null, "2026-10-05T10:00:00Z"), item("old", 50, null, "2026-10-02T10:00:00Z")];
    expect(recommendNext(tie)?.interview.id).toBe("old");
    expect(recommendNext([item("a", 75, null), item("b", 90, null)])).toBeNull();
    expect(recommendNext([])).toBeNull();
  });
});
