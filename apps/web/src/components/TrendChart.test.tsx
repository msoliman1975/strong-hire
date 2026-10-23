/** CU-7: trend points from own questions are marked, and a switch leaves them out. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { JobProgress } from "../api/types";
import { createQueryClient } from "../App";
import { server } from "../mocks/node";
import { JobTrend } from "./TrendChart";

const S1 = "00000000-0000-4000-8000-000000000001";
const S2 = "00000000-0000-4000-8000-000000000002";

function progress(excluded: boolean): JobProgress {
  return {
    job_target_id: "j1",
    snapshots: [
      { job_target_id: "j1", session_id: S1, competency: "ownership", score: 2.5, at: "2026-10-01T10:00:00Z" },
      { job_target_id: "j1", session_id: S2, competency: "ownership", score: excluded ? 2.75 : 3.5, at: "2026-10-08T10:00:00Z" },
    ],
    trends: [],
    next_session: null,
    next_custom_session: null,
    own_question_points: excluded ? [] : [{ session_id: S2, competency: "ownership", own_questions: 2, other_questions: 1 }],
    own_questions_excluded: excluded,
  };
}

describe("JobTrend", () => {
  it("CU-7: marks points with own questions and refetches without them on request", async () => {
    const asked: (string | null)[] = [];
    server.use(
      http.get("*/api/job-targets/:jobId/progress", ({ request }) => {
        const flag = new URL(request.url).searchParams.get("exclude_own_questions");
        asked.push(flag);
        return HttpResponse.json(progress(flag === "true"));
      }),
    );
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createQueryClient()}>
        <JobTrend jobId="j1" />
      </QueryClientProvider>,
    );
    const chart = await screen.findByRole("img", { name: "Ownership: 2.5, 3.5 (with your questions)" });
    expect(chart.querySelectorAll('[data-own="true"]')).toHaveLength(1);
    expect(screen.getByTestId("own-points-note")).toHaveTextContent("A ringed point includes scores from questions you wrote.");

    await user.click(screen.getByRole("checkbox", { name: "Hide scores from my own questions" }));
    expect(await screen.findByRole("img", { name: "Ownership: 2.5, 2.8" })).toBeInTheDocument();
    expect(screen.queryByTestId("own-points-note")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Hide scores from my own questions" })).toBeChecked();
    expect(asked).toEqual([null, "true"]);
  });

  it("CU-7: no switch when no point uses own questions", async () => {
    server.use(
      http.get("*/api/job-targets/:jobId/progress", () =>
        HttpResponse.json({ ...progress(false), own_question_points: [] }),
      ),
    );
    render(
      <QueryClientProvider client={createQueryClient()}>
        <JobTrend jobId="j1" />
      </QueryClientProvider>,
    );
    await screen.findByRole("img", { name: "Ownership: 2.5, 3.5" });
    expect(screen.queryByRole("checkbox", { name: "Hide scores from my own questions" })).not.toBeInTheDocument();
  });
});
