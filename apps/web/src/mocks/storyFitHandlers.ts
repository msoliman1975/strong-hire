/** MSW for the plan page's story fit table (ST-5, S23): GET /plan/{job}/{resume}/story-fit. */
import { http, HttpResponse } from "msw";

import type { StoryFitView } from "../pages/plan/StoryFitTable";

export const mockStoryFit: StoryFitView = {
  status: "ready",
  computed_at: "2026-10-05T10:00:00Z",
  rows: [
    {
      competency: "ownership",
      strength: "strong",
      story: { id: "story-1", title: "Payments outage", status: "proven" },
      reason: "You led the fix end to end and owned the follow-up.",
    },
    {
      competency: "impact",
      strength: "thin",
      story: { id: "story-1", title: "Payments outage", status: "proven" },
      reason: "The result has no number yet.",
    },
    {
      competency: "conflict_handling",
      strength: "missing",
      story: null,
      reason: "None of your stories shows this skill yet.",
    },
  ],
};

export const storyFitHandlers = () => [
  http.get("*/api/plan/:jobId/:resumeId/story-fit", () => HttpResponse.json(mockStoryFit)),
];
