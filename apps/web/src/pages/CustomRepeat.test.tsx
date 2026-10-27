/**
 * Custom interview, run again and recommended (docs/custom-interview-spec.md): "Run this setup
 * again" from the rehearsals view (CU-9, PR-3) and a recommended Custom session on the
 * dashboard (CU-10), against the MSW mocks of the real endpoints.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { gapApi } from "../api/gap";
import { jobTargetsApi, resumesApi } from "../api/inputs";
import type { SessionConfig, SessionRecord, Usage } from "../api/types";
import { AppRoutes, createQueryClient } from "../App";
import { FREE_USAGE, OPEN_STATUS } from "../mocks/db";
import { mockStore } from "../mocks/node";

const POSTING = "Senior Software Engineer at Stripe. Payments reliability, Python, Go. ".repeat(4);

const PAID: Usage = {
  ...FREE_USAGE,
  plan: "paid",
  status: "active",
  minutes_cap: 300,
  minutes_left: 300,
  free_interviews_left: 0,
  full_interviews_allowed: true,
};

const CUSTOM_CONFIG: SessionConfig = {
  interview_type: "custom",
  difficulty: "realistic",
  mode: "realistic",
  duration_min: 30,
  level: "senior",
  tone: "as_company",
  custom: {
    categories: [
      { category: "behavioral", share: 0.5, focus: ["Conflict with a peer"] },
      { category: "technical_qa", share: 0.5, focus: ["Kubernetes"] },
    ],
    questions: [
      {
        text: "Tell me about a time you disagreed with your manager.",
        category: "behavioral",
        competencies: ["conflict_handling"],
        must_ask: true,
        verbatim: false,
        saved_question_id: null,
      },
    ],
  },
};

function signedIn(email = "ana@example.com") {
  mockStore.db.users[email] = {
    id: "00000000-0000-4000-8000-0000000000a1",
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email,
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
}

function session(id: string, jobId: string, resumeId: string, config: SessionConfig, day: number): SessionRecord {
  return {
    id,
    job_target_id: jobId,
    resume_id: resumeId,
    config,
    channel: "voice",
    brief_ready: true,
    status: "completed",
    started_at: `2026-10-0${day}T10:00:00Z`,
    ended_at: `2026-10-0${day}T10:30:00Z`,
    minutes_billed: 30,
    failure_reason: null,
  };
}

/** A paid account with a read job, a confirmed CV, a ready gap report and the given sessions. */
async function seed(configs: SessionConfig[]) {
  signedIn();
  mockStore.db.usage = PAID;
  mockStore.db.siteStatus = { ...OPEN_STATUS };
  const { job_target: job } = await jobTargetsApi.create({ text: POSTING });
  await jobTargetsApi.get(job.id);
  const form = new FormData();
  form.append("text", "Ana Lopez. Backend engineer, seven years of Python.");
  const { resume } = await resumesApi.upload(form);
  const parsed = (await resumesApi.get(resume.id)).resume;
  if (parsed) await resumesApi.update(resume.id, parsed);
  await gapApi.start(job.id, { resume_id: resume.id });
  await gapApi.get(job.id);
  configs.forEach((config, i) => {
    mockStore.db.sessions.push(
      session(`00000000-0000-4000-8000-00000000e00${i + 1}`, job.id, resume.id, config, i + 3),
    );
  });
  return { job, resume };
}

function renderAt(path: string) {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

const behavioral: SessionConfig = { ...CUSTOM_CONFIG, interview_type: "behavioral", custom: null };

// These tests render the whole app; under a loaded test run they need more than the defaults.
const SLOW = { timeout: 4000 };

describe("Custom run again and recommendation", { timeout: 20_000 }, () => {
  it("CU-9: the rehearsals view runs an earlier Custom setup again, prefilled", async () => {
    const { job, resume } = await seed([behavioral, CUSTOM_CONFIG]);
    const user = renderAt(`/jobs/${job.id}/rehearse/${resume.id}`);
    const panel = await screen.findByRole("region", { name: "Your Custom setups" }, SLOW);
    expect(within(panel).getAllByTestId("custom-setup")).toHaveLength(1);
    expect(panel).toHaveTextContent("Behavioral, Verbal technical Q&A. 1 of your questions");
    await user.click(within(panel).getByRole("button", { name: /^Run this setup again/ }));

    expect(await screen.findByRole("heading", { name: "Set up your interview" }, SLOW)).toBeInTheDocument();
    expect(await screen.findByRole("radio", { name: /^Custom/ }, SLOW)).toBeChecked();
    expect(await screen.findByRole("button", { name: "Kubernetes" }, SLOW)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("own-question")).toHaveTextContent("Tell me about a time you disagreed with your manager.");
  });

  it("CU-9: the rehearsals view has no Custom panel without a Custom session", async () => {
    const { job, resume } = await seed([behavioral]);
    renderAt(`/jobs/${job.id}/rehearse/${resume.id}`);
    expect(await screen.findByRole("region", { name: "Where you stand" }, SLOW)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Your Custom setups" })).not.toBeInTheDocument();
  });

  it("CU-10: the dashboard recommends a Custom session and opens its setup prefilled", async () => {
    await seed([behavioral, { ...behavioral, interview_type: "technical_qa" }]);
    const user = renderAt("/");
    const card = await screen.findByTestId("custom-next", {}, SLOW);
    expect(within(card).getByRole("heading", { name: "Practice trade offs and conflict handling" })).toBeInTheDocument();
    expect(card).toHaveTextContent("Custom interview, Verbal technical Q&A, Behavioral, 30 minutes.");
    await user.click(within(card).getByRole("link", { name: "Set up this Custom interview" }));

    expect(await screen.findByRole("radio", { name: /^Custom/ }, SLOW)).toBeChecked();
    expect(await screen.findByRole("button", { name: "Trade offs" }, SLOW)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Idempotency" })).toHaveAttribute("aria-pressed", "true");
  });

  it("CU-10, CU-11: no Custom recommendation while Custom is locked for a free account", async () => {
    await seed([behavioral, { ...behavioral, interview_type: "technical_qa" }]);
    mockStore.db.usage = FREE_USAGE;
    mockStore.db.siteStatus = { ...OPEN_STATUS, custom_interview_access: "paid_only" };
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Your trend" }, SLOW)).toBeInTheDocument();
    expect(await screen.findByText("Next rehearsal", {}, SLOW)).toBeInTheDocument();
    expect(screen.queryByTestId("custom-next")).not.toBeInTheDocument();
  });
});
