/** Dev-only text interview page: create, open, answer, end, debrief (P7 text channel, PL-7). */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../App";
import { jobPosting, scorecardFor } from "../mocks/fixtures";
import { server } from "../mocks/node";
import { DevTextInterviewPage } from "./DevTextInterviewPage";

const CONFIG = {
  interview_type: "behavioral",
  difficulty: "realistic",
  mode: "coach",
  duration_min: 30,
  level: "senior",
};

const record = (brief_ready: boolean) => ({
  id: "s1",
  job_target_id: "j1",
  config: CONFIG,
  channel: "text",
  status: "created",
  brief_ready,
  started_at: null,
  ended_at: null,
  minutes_billed: 0,
});

const turn = (speaker: string, phase: string, text: string) => ({
  speaker,
  phase,
  text,
  start_ms: 0,
  end_ms: 0,
  question_ref: phase === "core" ? "q1" : null,
});

function useApi() {
  const calls: { path: string; body: unknown }[] = [];
  const job = {
    job_target: {
      id: "j1",
      status: "extracted",
      source_url: null,
      posting: jobPosting,
      level: "senior",
      company_id: null,
      company_slug: null,
      generic_mode: true,
      stage: null,
      context: null,
      created_at: "2026-10-01T10:00:00Z",
    },
    match_score: 60,
    gap_status: "ready",
    sessions_count: 0,
    last_session_at: null,
  };
  server.use(
    http.get("*/api/job-targets", () => HttpResponse.json([job])),
    http.post("*/api/sessions", async ({ request }) => {
      calls.push({ path: "create", body: await request.json() });
      return HttpResponse.json(record(true), { status: 201 });
    }),
    http.post("*/api/sessions/s1/text/open", () =>
      HttpResponse.json({ turns: [turn("interviewer", "intro", "Hi, I am Alex.")], ended: false, phase: "intro" }),
    ),
    http.post("*/api/sessions/s1/text/turn", async ({ request }) => {
      calls.push({ path: "turn", body: await request.json() });
      return HttpResponse.json({
        turns: [turn("interviewer", "wrap_up", "Thank you, that is all for today.")],
        ended: true,
        phase: "wrap_up",
      });
    }),
    http.post("*/api/sessions/s1/coach", async ({ request }) => {
      calls.push({ path: "coach", body: await request.json() });
      return HttpResponse.json({ turns: [turn("interviewer", "core", "Think about your own part.")], ended: false, phase: "core" });
    }),
    http.get("*/api/sessions/s1/debrief", () =>
      HttpResponse.json({
        session: { ...record(true), status: "completed" },
        status: "ready",
        scorecard: scorecardFor("behavioral", true),
        next_session: null,
        generic_mode: true,
        company_name: null,
        values_framework: null,
      }),
    ),
  );
  return calls;
}

function renderPage() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <DevTextInterviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DevTextInterviewPage", () => {
  it("runs a text interview from setup to the debrief", async () => {
    const calls = useApi();
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(await screen.findByLabelText("Mode"), "coach");
    await user.click(screen.getByRole("button", { name: "Start text interview" }));
    expect(await screen.findByText("Hi, I am Alex.")).toBeInTheDocument();
    expect(calls[0]).toEqual({
      path: "create",
      body: { job_target_id: "j1", config: { ...CONFIG }, channel: "text" },
    });

    await user.click(screen.getByRole("button", { name: "Hint" }));
    expect(await screen.findByText("Think about your own part.")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Your answer"), "I led the rollout.");
    await user.click(screen.getByRole("button", { name: "Send (Ctrl+Enter)" }));
    expect(await screen.findByText("I led the rollout.")).toBeInTheDocument();
    expect(await screen.findByText("Thank you, that is all for today.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "turn")?.body).toEqual({ text: "I led the rollout." });

    const signal = scorecardFor("behavioral", true).hire_signal;
    await waitFor(() => expect(screen.getByText(signal)).toBeInTheDocument());
    expect(screen.queryByLabelText("Your answer")).not.toBeInTheDocument();
  });
});
