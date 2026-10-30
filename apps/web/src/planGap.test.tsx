/**
 * The v2 gap report (owner feedback: the gap analysis is a key capability), with `v2_enabled` on,
 * against the MSW mocks end to end. U13 removed the retired plan page and its "Your plan" card;
 * PP-1 and PP-4 are covered on the role and interview pages (roles.test.tsx, test_plan_api.py).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { gapApi } from "./api/gap";
import { jobTargetsApi, resumesApi } from "./api/inputs";
import { AppRoutes, createQueryClient } from "./App";
import { GAP_COPY } from "./copy";
import { mockStore } from "./mocks/node";
import { setFeatureOverrides } from "./theme/features";

afterEach(() => setFeatureOverrides({}));

function signedIn() {
  const email = "ana@example.com";
  mockStore.db.users[email] = {
    id: "00000000-0000-4000-8000-0000000000a1",
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email,
    auth_provider: "password",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
  // Keep the tour out of these screens.
  globalThis.localStorage?.setItem("sh-tour-done-00000000-0000-4000-8000-0000000000a1", "x");
}

/** A job and a CV with a ready gap analysis. */
async function interview() {
  signedIn();
  const { job_target: job } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  await jobTargetsApi.get(job.id);
  const form = new FormData();
  form.append("text", "Backend engineer, seven years of Python.");
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  await gapApi.start(job.id, { resume_id: resume.id });
  await new Promise((r) => setTimeout(r, 10));
  const gap = await gapApi.get(job.id);
  return { jobId: job.id, resumeId: resume.id, gap };
}

function renderApp(path: string) {
  signedIn();
  setFeatureOverrides({ v2_enabled: true });
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

describe("gap report (v2)", () => {
  it("GA-1: the v2 report with the match score, strengths, gaps, probes and practice plan", async () => {
    const { jobId, gap } = await interview();
    renderApp(`/jobs/${jobId}/gap-report`);
    expect(await screen.findByRole("heading", { level: 1, name: "Gap report" })).toBeInTheDocument();
    expect(await screen.findByTestId("match-score")).toHaveTextContent(String(gap.analysis?.match_score));
    for (const name of ["Match score", "Strengths", GAP_COPY.heading, "Where they'll probe", "Practice plan"]) {
      expect(screen.getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    // U07: the plan page is retired; the report goes back to the role page.
    expect(screen.getByRole("link", { name: "← Back to the role" })).toHaveAttribute("href", `/roles/${jobId}`);
  });

  it("R1: an earlier report link (/jobs/:id/gap?report=) opens the v2 report too", async () => {
    const { jobId, gap } = await interview();
    renderApp(`/jobs/${jobId}/gap?report=${gap.id}`);
    expect(await screen.findByRole("heading", { level: 1, name: "Gap report" })).toBeInTheDocument();
  });
});

describe("gap analysis on Interviews", () => {
  it("GA-1: each ready interview shows its match score with View gap report", async () => {
    const { jobId } = await interview();
    renderApp("/jobs");
    const list = await screen.findByRole("list", { name: "Your interviews" });
    const card = within(list).getAllByTestId("interview-card")[0];
    expect(await within(card).findByText(/Match/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "View gap report" })).toHaveAttribute("href", `/jobs/${jobId}/gap-report`);
  });
});
