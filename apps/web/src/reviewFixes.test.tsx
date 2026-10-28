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
import { latestResume } from "./pages/home/ResumesCard";
import { workReasons } from "./pages/progress/StoriesToWorkOn";
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
    // An interview with no CV yet: its one primary button goes to the CV step.
    expect(within(card).getByRole("link", { name: "Get ready to rehearse" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/jobs\/.+\/resume$/),
    );
    expect(screen.getAllByRole("link", { name: "Add a job description" })[0]).toHaveAttribute("href", "/jobs/new");
  });

  it("PP-3: with no interviews it says what to do, with Add a job description", async () => {
    renderApp("/jobs");
    expect(await screen.findByText(/Add the job description for the interview you have/)).toBeInTheDocument();
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

describe("Resumes card on Home (v2)", () => {
  it("LB-1: shows the resumes on file and the latest, with Check a resume when it needs a check", async () => {
    await addResume("First CV text, Python and Go.");
    await addResume("Second CV text, Python, Go and Kafka.");
    renderApp("/");
    const card = await screen.findByRole("region", { name: "The CV your interviews are measured against." });
    expect(await within(card).findByText("On file")).toBeInTheDocument();
    expect(within(card).getByText("2")).toBeInTheDocument();
    expect(card).toHaveTextContent("Needs a check");
    expect(within(card).getByRole("link", { name: "Check a resume" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/resumes\/.+\/check$/),
    );
    expect(within(card).getByRole("link", { name: "Add a resume" })).toHaveAttribute("href", "/resumes");
  });

  it("LB-1: with no resume, the card offers Add a resume", async () => {
    renderApp("/");
    const card = await screen.findByRole("region", { name: "The CV your interviews are measured against." });
    expect(await within(card).findByText(/Add the CV you will interview with/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Add a resume" })).toHaveAttribute("href", "/resumes");
    expect(within(card).queryByRole("link", { name: "Check a resume" })).toBeNull();
  });

  it("LB-1: the latest resume is the newest one not deleted", () => {
    const r = (id: string, at: string, deleted = false) =>
      ({ id, uploaded_at: at, deleted }) as Parameters<typeof latestResume>[0][number];
    expect(latestResume([r("a", "2026-10-01"), r("b", "2026-10-03", true), r("c", "2026-10-02")])?.id).toBe("c");
    expect(latestResume([])).toBeNull();
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

  it("ST-3: lists the stories that need work (drafts, missing parts, coach notes), each with Work on it", async () => {
    resetMockStories([PROVEN, DRAFT, NOTED]);
    renderApp("/reports");
    expect(await screen.findByRole("heading", { level: 1, name: "Progress" })).toBeInTheDocument();
    const rows = await screen.findAllByTestId("story-to-work-on");
    expect(rows.map((r) => within(r).getAllByRole("link")[0].textContent)).toEqual(["Pushback from platform", "Vendor"]);
    expect(rows[0]).toHaveTextContent("Not proven yet · Missing stakes, your action, result, reflection");
    expect(rows[1]).toHaveTextContent("1 coach note");
    expect(within(rows[0]).getByRole("link", { name: "Work on it" })).toHaveAttribute("href", "/coach/new?story=s2");
    // The reports stay below.
    expect(screen.getByRole("region", { name: "Report list" })).toBeInTheDocument();
  });

  it("ST-3: a proven, complete story with no coach notes needs no work", () => {
    expect(workReasons(PROVEN)).toEqual([]);
  });

  it("FL-1: with v2 off, the page is still Reports, with no story list", async () => {
    resetMockStories([DRAFT]);
    renderApp("/reports", false);
    expect(await screen.findByRole("heading", { level: 1, name: "Reports" })).toBeInTheDocument();
    expect(screen.queryByTestId("story-to-work-on")).toBeNull();
  });
});

describe("Interview path (v2)", () => {
  it("PP-1: confirming the CV leads to the context step, whose button opens the plan", async () => {
    const job = await addJob();
    const resume = await addResume();
    const user = renderApp(`/jobs/${job.id}/resume/${resume.id}/check`);
    await user.click(await screen.findByRole("button", { name: "Confirm and continue" }));
    expect(await screen.findByRole("button", { name: "Save and open my plan" })).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(`/jobs/${job.id}/context?resume=${resume.id}`);
  });
});
