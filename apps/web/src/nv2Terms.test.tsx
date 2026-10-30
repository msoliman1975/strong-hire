/**
 * NV-2: with `v2_enabled` on, user-facing copy says resume, never CV. Renders the v2 routes in
 * mock mode, with a resume and a job on file, and searches the rendered text.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "./api/inputs";
import { AppRoutes, createQueryClient } from "./App";
import { mockStore } from "./mocks/node";
import { setFeatureOverrides } from "./theme/features";

const USER_ID = "00000000-0000-4000-8000-0000000000a1";
const CV_WORD = /\bCVs?\b/;

beforeEach(() => {
  globalThis.localStorage?.clear();
  globalThis.localStorage?.setItem(`sh-tour-done-${USER_ID}`, "x");
  const email = "ana@example.com";
  mockStore.db.users[email] = {
    id: USER_ID,
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email,
    auth_provider: "password",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
  setFeatureOverrides({ v2_enabled: true });
});
afterEach(() => setFeatureOverrides({}));

async function seed() {
  const form = new FormData();
  form.append("text", "Backend engineer, Python and Go. Led the move of 30 services to PostgreSQL.");
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  // A pasted resume gets the core default name "CV <date>": a stored name the user can change,
  // not interface copy (U04 follow-up). Name it, so the test checks the copy only.
  await resumesApi.rename(resume.id, "Ana Lopez resume");
  const { job_target: job } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  await jobTargetsApi.get(job.id);
  return { resumeId: resume.id, jobId: job.id };
}

/** The visible text of the page once its main heading and data have loaded. */
async function textAt(path: string): Promise<string> {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("banner", { name: "Top bar" });
  await screen.findAllByRole("heading", { level: 1 });
  // Let the page's queries settle.
  await new Promise((r) => setTimeout(r, 300));
  const text = document.body.textContent ?? "";
  cleanup();
  return text;
}

describe("NV-2 terms", () => {
  it("NV-2: no v2 screen says CV", async () => {
    const { resumeId, jobId } = await seed();
    for (const path of [
      "/",
      "/resumes",
      `/resumes/${resumeId}/check`,
      "/roles",
      "/rehearsals",
      "/stories",
      `/interviews/${jobId}/${resumeId}`,
      `/jobs/${jobId}/gap-report`,
      "/help",
    ]) {
      const text = await textAt(path);
      expect(text.match(new RegExp(`.{0,60}${CV_WORD.source}.{0,40}`))?.[0] ?? null, path).toBeNull();
      expect(text.length, path).toBeGreaterThan(200);
    }
  });
});
