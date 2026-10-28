/** TR-1: the transcript page, and the debrief's "Read the transcript" link (behind v2_enabled). */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import type { Debrief } from "../../api/types";
import { createQueryClient } from "../../App";
import { scorecardFor } from "../../mocks/fixtures";
import { server } from "../../mocks/node";
import { mockTranscript } from "../../mocks/transcriptHandlers";
import { setFeatureOverrides } from "../../theme/features";
import { DebriefPage } from "../DebriefPage";
import { offset, TranscriptPage } from "./TranscriptPage";

afterEach(() => setFeatureOverrides({}));

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
          <Route path="/sessions/:sessionId/transcript" element={<TranscriptPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const debrief: Debrief = {
  session: {
    id: "s1",
    job_target_id: "j1",
    config: { interview_type: "behavioral", difficulty: "realistic", mode: "realistic", duration_min: 30, level: "senior", custom: null, tone: "as_company" },
    status: "completed",
    started_at: "2026-10-01T10:00:00Z",
    ended_at: "2026-10-01T10:30:00Z",
    minutes_billed: 30,
    failure_reason: null,
  },
  status: "ready",
  scorecard: scorecardFor("behavioral", true),
  next_session: null,
  next_custom_session: null,
  generic_mode: true,
  company_name: null,
  company_slug: null,
  values_framework: null,
  questions: [],
};

describe("transcript page (TR-1)", () => {
  it("TR-1: shows every turn in order, grouped by question, with speaker and time", async () => {
    renderAt("/sessions/s1/transcript");
    const list = await screen.findByRole("list", { name: "Transcript" });
    const groups = within(list).getAllByRole("heading", { level: 2 });
    expect(groups.map((h) => h.textContent)).toEqual([
      "Intro",
      "Question 1Tell me about a time you disagreed with a teammate.",
      "Wrap-up",
    ]);
    const turns = mockTranscript("s1").groups.flatMap((g) => g.turns);
    const shown = [...list.querySelectorAll(".transcript__text")].map((p) => p.textContent);
    expect(shown).toEqual(turns.map((t) => t.text));
    expect(screen.getAllByText("You")).toHaveLength(3);
    expect(screen.getByText("1:08")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the debrief" })).toHaveAttribute("href", "/sessions/s1/debrief");
  });

  it("TR-1: another user's session (404) says it was not found", async () => {
    server.use(
      http.get("*/api/sessions/:sessionId/transcript", () =>
        HttpResponse.json({ detail: "Session not found" }, { status: 404 }),
      ),
    );
    renderAt("/sessions/other/transcript");
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not find this interview.");
    expect(screen.queryByRole("list", { name: "Transcript" })).not.toBeInTheDocument();
  });

  it("TR-1: a session that has not ended (409) says the transcript comes later", async () => {
    server.use(
      http.get("*/api/sessions/:sessionId/transcript", () => HttpResponse.json({ detail: "not_ended" }, { status: 409 })),
    );
    renderAt("/sessions/s1/transcript");
    expect(await screen.findByTestId("transcript-not-ended")).toHaveTextContent("has not finished");
  });

  it("TR-1: the debrief links to the transcript when v2 is on, and not before", async () => {
    server.use(http.get("*/api/sessions/:sessionId/debrief", () => HttpResponse.json(debrief)));
    const first = renderAt("/sessions/s1/debrief");
    await screen.findByRole("heading", { name: "Debrief", level: 1 });
    expect(screen.queryByRole("link", { name: "Read the transcript" })).not.toBeInTheDocument();
    first.unmount();

    setFeatureOverrides({ v2_enabled: true });
    renderAt("/sessions/s1/debrief");
    const link = await screen.findByRole("link", { name: "Read the transcript" });
    expect(link).toHaveAttribute("href", "/sessions/s1/transcript");
    await userEvent.click(link);
    expect(await screen.findByRole("list", { name: "Transcript" })).toBeInTheDocument();
  });

  it("formats time offsets", () => {
    expect([offset(0), offset(68_000), offset(3_725_000)]).toEqual(["0:00", "1:08", "1:02:05"]);
  });
});
