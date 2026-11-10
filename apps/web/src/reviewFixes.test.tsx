/**
 * The owner's review fixes, with `v2_enabled` on and v1 kept with it off: the Interviews page
 * (PP-3), the Resumes card on Home (LB-1), the stories that need work on Progress (ST-3), and the
 * CV check that leads on to the context step and the plan (PP-1).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "./api/inputs";
import { AppRoutes, createQueryClient } from "./App";
import { mockStore } from "./mocks/node";
import { mockStory, resetMockStories } from "./mocks/storyHandlers";
import { setFeatureOverrides } from "./theme/features";

afterEach(() => setFeatureOverrides({}));

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
    tracing_consent: false,
    tracing_consent_available: false,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
}

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderApp(path: string, v2 = true) {
  signedIn();
  setFeatureOverrides({ v2_enabled: v2 });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

async function addJob() {
  signedIn();
  const { job_target: job } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  await jobTargetsApi.get(job.id);
  return job;
}

async function addResume(text = "Backend engineer, seven years of Python.") {
  signedIn();
  const form = new FormData();
  form.append("text", text);
  const { resume } = await resumesApi.upload(form);
  return resumesApi.get(resume.id);
}

describe("Interviews page (v2)", () => {
  it("PP-3: the Interviews menu opens a list of your interviews with Add a job description, not the add form", async () => {
    await addJob();
    renderApp("/jobs");
    expect(await screen.findByRole("heading", { level: 1, name: "Interviews" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Your interviews" });
    const card = within(list).getAllByTestId("interview-card")[0];
    // An interview with no CV yet is a draft: Continue setup goes to the CV step.
    expect(card).toHaveTextContent("Draft ·");
    expect(card).toHaveTextContent("Next: pick the resume you sent them.");
    expect(within(card).getByRole("link", { name: "Continue setup →" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/jobs\/.+\/resume$/),
    );
    expect(screen.getAllByRole("link", { name: "Add a job description" })[0]).toHaveAttribute("href", "/jobs/new");
  });

  it("PP-3: with no interviews it says what to do, with Add a job description", async () => {
    renderApp("/jobs");
    expect(await screen.findByText(/Paste the job description for an interview you have/)).toBeInTheDocument();
  });

  it("LB-2: the saved job descriptions stay one click away", async () => {
    await addJob();
    const user = renderApp("/jobs");
    await user.click(await screen.findByRole("button", { name: "Manage saved job descriptions" }));
    expect(await screen.findByRole("heading", { name: "Saved job descriptions" })).toBeInTheDocument();
  });

  it("FL-1: with v2 off, /jobs is still the v1 Job descriptions page", async () => {
    renderApp("/jobs", false);
    expect(await screen.findByRole("heading", { level: 1, name: "Job descriptions" })).toBeInTheDocument();
  });
});

describe("Progress page (v2)", () => {
  const PROVEN = mockStory({
    id: "s1",
    title: "Checkout migration",
    context: "c",
    stakes: "s",
    action: "a",
    result: "r",
    reflection: "f",
    status: "proven",
    skills: ["ownership"],
  });
  const DRAFT = mockStory({ id: "s2", title: "Pushback from platform", context: "c" });
  const NOTED = mockStory({
    ...PROVEN,
    id: "s3",
    title: "Vendor",
    notes: [{ text: "Say the number first.", at: "2026-10-05T09:00:00Z", session_id: null, question_ref: null }],
  });

  it("NV-4: Reports has three lists (gap reports, debriefs, stories) with their counts; Stories shows every story with its status", async () => {
    resetMockStories([PROVEN, DRAFT, NOTED]);
    const user = renderApp("/reports");
    expect(await screen.findByRole("heading", { level: 1, name: "Reports" })).toBeInTheDocument();
    const views = screen.getByRole("group", { name: "Show" });
    expect(within(views).getByRole("button", { name: /^Gap reports/ })).toHaveAttribute("aria-pressed", "true");
    await within(views).findByRole("button", { name: "Stories · 3" });
    // No role cards any more.
    expect(document.querySelector(".sx-summary")).toBeNull();

    await user.click(within(views).getByRole("button", { name: "Stories · 3" }));
    expect(screen.getByTestId("where")).toHaveTextContent("type=stories");
    const list = await screen.findByRole("list", { name: "Stories" });
    const links = within(list).getAllByRole("link");
    expect(links).toHaveLength(3);
    const byTitle = (t: string) => links.find((l) => l.textContent?.includes(t)) as HTMLElement;
    expect(byTitle("Checkout migration")).toHaveTextContent("Proven");
    expect(byTitle("Pushback from platform")).toHaveTextContent("Draft");
    expect(byTitle("Vendor")).toHaveTextContent("1 coach note");
    expect(byTitle("Pushback from platform")).toHaveAttribute("href", "/stories/s2");
    // The target role filter is for reports only.
    expect(screen.queryByLabelText("Target role")).toBeNull();
  });

  it("FL-1: with v2 off, the page is still Reports, with no story list", async () => {
    resetMockStories([DRAFT]);
    renderApp("/reports", false);
    expect(await screen.findByRole("heading", { level: 1, name: "Reports" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Stories" })).toBeNull();
  });
});

describe("Interview path (v2)", () => {
  it("PP-1: confirming the CV leads to the context step, whose button opens the plan", async () => {
    const job = await addJob();
    const resume = await addResume();
    const user = renderApp(`/jobs/${job.id}/resume/${resume.id}/check`);
    await user.click((await screen.findAllByRole("button", { name: "Continue to your interview plan" }))[0]);
    expect(await screen.findByRole("button", { name: "Save and open my plan" })).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(`/jobs/${job.id}/context?resume=${resume.id}`);
  });
});
