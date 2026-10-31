/**
 * U05: the first run (ON-1 to ON-6) and the resume pages (RM-1, RM-3), with v2 on, against the
 * MSW mocks.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "../../api/inputs";
import { AppRoutes, createQueryClient } from "../../App";
import { mockStore } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";
import { setFirstRunGate } from "./gate";

const USER_ID = "00000000-0000-4000-8000-0000000000a1";
const EMAIL = "ana@example.com";
const RESUME_TEXT = "Backend engineer, Python and Go. Led the move of 30 services to PostgreSQL.";

function Where() {
  const { pathname, search } = useLocation();
  return <span data-testid="where">{pathname + search}</span>;
}

beforeEach(() => {
  globalThis.localStorage?.clear();
  globalThis.localStorage?.setItem(`sh-tour-done-${USER_ID}`, "x");
  mockStore.db.users[EMAIL] = {
    id: USER_ID,
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email: EMAIL,
    auth_provider: "password",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email: EMAIL, userEmail: EMAIL };
  setFeatureOverrides({ v2_enabled: true });
  setFirstRunGate(true);
});
afterEach(() => setFeatureOverrides({}));

function renderApp(path: string) {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

async function addResume() {
  const form = new FormData();
  form.append("text", RESUME_TEXT);
  const { resume } = await resumesApi.upload(form);
  return resumesApi.get(resume.id);
}

const where = () => screen.getByTestId("where").textContent ?? "";

describe("first run", () => {
  it("ON-1: a user with no resume lands on Start, with the three inputs and the steps", async () => {
    const user = renderApp("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Start with your resume" })).toBeInTheDocument();
    expect(where()).toBe("/start");
    const steps = screen.getByRole("list", { name: "Setup steps" });
    expect(within(steps).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Done: Profile",
      "Your resume",
      "Plan style",
    ]);
    expect(within(steps).getByText("Your resume")).toHaveAttribute("aria-current", "step");
    // No rail during setup.
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
    // 1 a file, 2 pasted text, 3 pasted LinkedIn experience (the same text path).
    expect(screen.getByLabelText("Resume file")).toHaveAttribute("type", "file");
    expect(screen.getByLabelText("Or paste your resume text")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Paste your LinkedIn experience" }));
    const linkedin = screen.getByLabelText("Or paste your LinkedIn experience");
    await user.type(linkedin, RESUME_TEXT);
    await user.click(screen.getByRole("button", { name: "Read my resume" }));
    await waitFor(() => expect(where()).toMatch(/^\/start\/(reading|ready)\//));
  });

  it("ON-1: Read my resume with nothing says what to add", async () => {
    const user = renderApp("/start");
    await user.click(await screen.findByRole("button", { name: "Read my resume" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a file or paste your resume first.");
  });

  it("ON-2: the reading screen shows Strova analysing and moves on once the resume is read", async () => {
    const form = new FormData();
    form.append("text", RESUME_TEXT);
    const { resume, job } = await resumesApi.upload(form);
    // Keep the mock reading job running until the screen has been checked.
    const task = Object.values(mockStore.db.tasks).find((t) => t.entityId === resume.id);
    if (task) task.readyAt = Date.now() + 60_000;
    const record = mockStore.db.resumes.find((r) => r.id === resume.id);
    if (record) Object.assign(record, { status: "pending", resume: null });
    renderApp(`/start/reading/${resume.id}?task=${job?.id ?? ""}`);
    const heading = await screen.findByRole("heading", { level: 1, name: "Strova is reading your resume" });
    expect(heading.closest("[role=status]")).not.toBeNull();
    expect(screen.getByRole("img", { name: "Strova is analysing" })).toHaveAttribute("width", "160");
    if (task) task.readyAt = 0;
    await waitFor(() => expect(where()).toBe(`/start/ready/${resume.id}`), { timeout: 4000 });
  });

  it("ON-2: a refused file shows the reason and Try another file", async () => {
    const form = new FormData();
    form.append("text", "We are hiring a Senior Software Engineer. Requirements: 5 years of Python.");
    const { resume, job } = await resumesApi.upload(form);
    renderApp(`/start/reading/${resume.id}?task=${job?.id ?? ""}`);
    expect(await screen.findByRole("heading", { name: "Strova could not read that resume" }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("alert")).not.toBeEmptyDOMElement();
    expect(screen.getByRole("link", { name: "Try another file" })).toHaveAttribute("href", "/start");
  });

  it("ON-3: the results show Breakdown, Resume issues and Story ideas collapsed, with counts and links", async () => {
    const resume = await addResume();
    const user = renderApp(`/start/ready/${resume.id}`);
    expect(await screen.findByRole("heading", { level: 1, name: "Here is what your resume shows" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Strova is coaching" })).toHaveAttribute("width", "88");
    const folds = document.querySelectorAll("details");
    expect(folds).toHaveLength(3);
    for (const d of folds) expect(d).not.toHaveAttribute("open");
    const titles = [...folds].map((d) => d.querySelector("summary h2")?.textContent);
    expect(titles[0]).toMatch(/^\d+ roles? · \d+ achievements? · \d+ skills?$/);
    await waitFor(() => expect(folds[1].querySelector("summary h2")?.textContent).toMatch(/to look at$|^Nothing to fix$/));
    await waitFor(() => expect(folds[2].querySelector("summary h2")?.textContent).toMatch(/^\d+ ideas?$/));
    await user.click(within(folds[0] as HTMLElement).getByText("Show"));
    expect(folds[0]).toHaveAttribute("open");
    expect(within(folds[0] as HTMLElement).getByRole("link", { name: "Open breakdown and issues" })).toHaveAttribute(
      "href",
      `/start/check/${resume.id}`,
    );
    expect(within(folds[2] as HTMLElement).getByRole("link", { name: "Open Career Stories" })).toHaveAttribute("href", "/stories");
    expect(screen.getByText(/One more question, then you're in\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue" })).toHaveAttribute("href", "/start/plan-style");
  });

  it("ON-4: breakdown and issues on one screen, with fix and accept, Back and Continue", async () => {
    const resume = await addResume();
    const record = mockStore.db.resumes.find((r) => r.id === resume.id);
    if (record?.resume) record.resume = { ...record.resume, summary: "Backend engineer." };
    const user = renderApp(`/start/check/${resume.id}`);
    expect(await screen.findByRole("heading", { level: 1, name: "Breakdown and issues" })).toBeInTheDocument();
    const breakdown = screen.getByRole("region", { name: "Breakdown" });
    expect(within(breakdown).getByRole("link", { name: "Edit" })).toHaveAttribute("href", `/resumes/${resume.id}/check`);
    const issues = screen.getByRole("region", { name: "Issues" });
    await within(issues).findByText("A very short summary");
    expect(within(issues).getByRole("link", { name: "Add to the summary" })).toHaveAttribute("href", `/resumes/${resume.id}/check`);
    await user.click(within(issues).getAllByRole("button", { name: /^Accept/ })[0]);
    await waitFor(() => expect(within(issues).getByText(/\d+ open · 1 accepted/)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Continue" })).toHaveAttribute("href", "/start/plan-style");
    expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute("href", `/start/ready/${resume.id}`);
  });

  it("ON-5: the plan style screen shows what the plan covers now and saves the style", async () => {
    await addResume();
    const user = renderApp("/start/plan-style");
    const covers = await screen.findByTestId("covers-now");
    expect(covers).toHaveTextContent("Complete your stories");
    expect(covers).toHaveTextContent("Fix your resume findings");
    expect(covers).toHaveTextContent("Mock interviews join your plan once you add a target role.");
    const weekly = screen.getByRole("button", { name: /Weekly plan/ });
    const checklist = screen.getByRole("button", { name: /Readiness checklist/ });
    expect(weekly).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Use the weekly plan" })).toBeInTheDocument();
    await user.click(checklist);
    expect(checklist).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Use the checklist" }));
    await waitFor(() => expect(where()).toBe("/start/what-first"));
    expect(mockStore.db.profiles[EMAIL]?.plan_style).toBe("checklist");
  });

  it("ON-5: a user with a resume but no plan style resumes at the plan style screen", async () => {
    await addResume();
    renderApp("/");
    expect(await screen.findByRole("heading", { level: 1, name: "How do you like to work?" })).toBeInTheDocument();
    expect(where()).toBe("/start/plan-style");
  });

  it("ON-6: what first offers the two paths with the start-anywhere copy and the two links", async () => {
    await addResume();
    renderApp("/start/what-first");
    expect(await screen.findByRole("heading", { level: 1, name: "What would you like to do first?" })).toBeInTheDocument();
    expect(screen.getByText(/Your resume and your plan are ready, so you can start anywhere\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /I'm applying to a role/ })).toHaveTextContent("Add a target role");
    const craft = screen.getByRole("link", { name: /Build my stories/ });
    expect(craft).toHaveTextContent("Craft a story with Strova");
    expect(craft.getAttribute("href")).toMatch(/^\/coach\/new/);
    expect(screen.getByRole("link", { name: "fix my resume first" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "go to Home" })).toHaveAttribute("href", "/");
  });
});

describe("resume pages", () => {
  it("RM-1: the resumes page is titled with the first name and marks the main resume", async () => {
    const first = await addResume();
    const second = await addResume();
    if (mockStore.db.profiles[EMAIL]) mockStore.db.profiles[EMAIL].plan_style = "weekly";
    else mockStore.db.profiles[EMAIL] = { ...(await import("../../mocks/handlers")).EMPTY_PROFILE, plan_style: "weekly" };
    const user = renderApp("/resumes");
    expect(await screen.findByRole("heading", { level: 1, name: "Ana's Resumes" })).toBeInTheDocument();
    const card = (await screen.findByText("Main")).closest(".sx-card") as HTMLElement;
    expect(within(card).getAllByRole("link", { name: /^Open / })).toHaveLength(2);
    const main = screen.getByText("Main");
    expect(main.closest(".sx-list-row")).toHaveTextContent(first.name ?? "");
    expect(await within(main.closest(".sx-list-row") as HTMLElement).findByText(/Not used by a role/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Make main" }));
    await waitFor(() => expect(screen.getByText("Main").closest(".sx-list-row")).toHaveTextContent(second.name ?? ""));
  });

  it("RM-3: the resume page has breakdown and issues first, then Strova's story ideas, closed with their counts", async () => {
    const resume = await addResume();
    mockStore.db.profiles[EMAIL] = { ...(await import("../../mocks/handlers")).EMPTY_PROFILE, plan_style: "weekly" };
    const user = renderApp(`/resumes/${resume.id}`);
    expect(await screen.findByRole("heading", { level: 1, name: resume.name ?? "" })).toBeInTheDocument();
    expect(screen.getByText("Main resume")).toBeInTheDocument();
    const ideas = await screen.findByRole("group", { name: "Story ideas from this resume" });
    const breakdown = screen.getByRole("region", { name: "Breakdown" });
    const issuesCard = screen.getByRole("region", { name: "Resume issues" });
    // The fix and accept actions are real buttons (filled or outlined), not plain text.
    const accept = await within(issuesCard).findAllByRole("button", { name: "Accept as it is" });
    expect(accept[0]).toHaveClass("sx-btn", "ghost");
    expect(within(issuesCard).getAllByRole("link")[0]).toHaveClass("sx-btn");
    expect(within(issuesCard).getAllByRole("link")[0]).not.toHaveClass("quiet");
    expect(breakdown.compareDocumentPosition(ideas) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(ideas).not.toHaveAttribute("open");
    expect(ideas).toHaveTextContent(/Strova's findings/);
    await waitFor(() => expect(within(ideas).getByTestId("ideas-counts")).toHaveTextContent(/^\d+ ideas?/));
    await user.click(within(ideas).getByText("Story ideas from this resume"));
    expect(ideas).toHaveAttribute("open");
    const craft = await within(ideas).findAllByRole("link", { name: "Craft with Strova" });
    expect(craft[0].getAttribute("href")).toMatch(/^\/coach\/new\?resume=/);
    const before = craft.length;
    await user.click(within(ideas).getAllByRole("button", { name: "Not a story" })[0]);
    await waitFor(() => expect(within(ideas).queryAllByRole("link", { name: "Craft with Strova" })).toHaveLength(before - 1));
    await act(async () => undefined);
  });

  it("RM-3, SG-6: the resume page says which roles use it, and Strova's resume-line rewrite adds, undoes and dismisses", async () => {
    const resume = await addResume();
    const { job_target: created } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
    const job = await jobTargetsApi.get(created.id);
    await fetch(`${location.origin}/api/roles/${job.id}/interviews`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ interview_types: ["behavioral"] }),
    });
    const user = renderApp(`/resumes/${resume.id}`);
    await screen.findByRole("heading", { level: 1, name: resume.name ?? "" });
    const usedBy = await screen.findByText(/^Used by/);
    expect(within(usedBy).getByRole("link")).toHaveAttribute("href", `/roles/${job.id}`);
    const card = await screen.findByRole("region", { name: "Strova suggests a resume line" });
    expect(card).toHaveTextContent("Strova suggests · from your stories");
    expect(card.querySelector("ins")?.textContent).toMatch(/zero failed payments/);
    await user.click(within(card).getByRole("button", { name: "Add to resume" }));
    expect(await within(card).findByText("Added to your resume.")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Undo" }));
    await user.click(await within(card).findByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Strova suggests a resume line" })).toBeNull());
  });
});
