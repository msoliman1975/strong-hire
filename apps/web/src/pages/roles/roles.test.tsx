/**
 * U07: target roles (TG-1, TG-2, TG-4), rehearsals (RH-4) and the interview page (RH-3), with v2
 * on, against the MSW mocks. Also the coverage moved from the retired plan page: PP-2 (the date
 * chip), PP-4 (the take settings) and RD-3 (readiness is a practice estimate).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { gapApi } from "../../api/gap";
import { jobTargetsApi, resumesApi } from "../../api/inputs";
import type { SessionRecord } from "../../api/types";
import { AppRoutes, createQueryClient } from "../../App";
import { EMPTY_PROFILE } from "../../mocks/handlers";
import { mockStore } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";

const USER_ID = "00000000-0000-4000-8000-0000000000a1";
const EMAIL = "ana@example.com";

function Where() {
  const { pathname } = useLocation();
  return <span data-testid="where">{pathname}</span>;
}

beforeEach(() => {
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
  mockStore.db.profiles[EMAIL] = { ...EMPTY_PROFILE, plan_style: "weekly", target_level: "senior" };
  setFeatureOverrides({ v2_enabled: true });
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

async function roleWithInterviews(...types: string[]) {
  const form = new FormData();
  form.append("text", "Backend engineer, Python and Go. Led the move of 30 services to PostgreSQL.");
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  const { job_target: created } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  const job = await jobTargetsApi.get(created.id);
  const resp = await fetch(`${location.origin}/api/roles/${job.id}/interviews`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ interview_types: types.length ? types : ["behavioral", "hiring_manager"] }),
  });
  const interviews = (await resp.json()) as { id: string; interview_type: string }[];
  // A take needs the role and resume's gap analysis (PR-3), as every session does.
  await gapApi.start(job.id, { resume_id: resume.id });
  await gapApi.get(job.id);
  return { job, resumeId: resume.id, interviews };
}

describe("target roles", () => {
  it("TG-1: each role shows its date chip, resume, and one readiness bar per interview", async () => {
    const { job } = await roleWithInterviews("behavioral", "hiring_manager");
    renderApp("/roles");
    expect(await screen.findByRole("heading", { level: 1, name: "Target roles" })).toBeInTheDocument();
    const c = await waitFor(() => {
      const found = screen.getAllByRole("link").find((a) => a.getAttribute("href") === `/roles/${job.id}`);
      expect(found).toBeDefined();
      return found as HTMLElement;
    });
    await within(c).findAllByRole("meter");
    expect(within(c).getByText("No date yet")).toBeInTheDocument();
    expect(c).toHaveTextContent("Main resume");
    expect(within(c).getAllByRole("meter")).toHaveLength(2);
    expect(within(c).getAllByText("Not started")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Add a target role" })).toHaveAttribute("href", "/roles/new");
  });

  it("TG-2: Back from Check the role returns to the posting as typed; Continue goes on without reading it again", async () => {
    const user = renderApp("/roles/new");
    await user.click(await screen.findByRole("button", { name: "paste the text" }));
    const text = "Senior engineer, payments. ".repeat(10);
    await user.click(screen.getByRole("textbox", { name: "Job posting text" }));
    await user.paste(text);
    await user.click(screen.getByRole("button", { name: "Read the posting" }));
    await screen.findByRole("textbox", { name: "Company" }, { timeout: 4000 });
    const jobs = mockStore.db.jobs.length;
    await user.click(screen.getByRole("button", { name: "Back" }));
    // Step 1 stays open, with the text kept.
    const box = await screen.findByRole("textbox", { name: "Job posting text" });
    expect(box).toHaveValue(text);
    await new Promise((r) => setTimeout(r, 300));
    expect(screen.queryByRole("textbox", { name: "Company" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("textbox", { name: "Company" })).toBeInTheDocument();
    expect(mockStore.db.jobs.length).toBe(jobs);
  });

  it("TG-2: add a role in three steps: posting, check, interviews; Create the role opens the role page", async () => {
    const form = new FormData();
    form.append("text", "Backend engineer, Python and Go.");
    await resumesApi.upload(form);
    const user = renderApp("/roles/new");
    await user.click(await screen.findByRole("button", { name: "paste the text" }));
    await user.click(screen.getByRole("textbox", { name: "Job posting text" }));
    await user.paste("Senior engineer, payments. ".repeat(10));
    await user.click(screen.getByRole("button", { name: "Read the posting" }));
    // 2: check the role.
    const company = await screen.findByRole("textbox", { name: "Company" }, { timeout: 4000 });
    expect(company).not.toHaveValue("");
    expect(screen.getByLabelText("Interview date (optional)")).toHaveAttribute("type", "date");
    await user.click(screen.getByRole("button", { name: "Looks right" }));
    // 3: the interviews Strova suggests, the usual ones kept.
    const behavioral = await screen.findByRole("checkbox", { name: /Behavioral/ });
    expect(behavioral).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Recruiter screen/ })).not.toBeChecked();
    expect(screen.getByText(/Measured against:/)).toHaveTextContent("(main)");
    await user.click(screen.getByRole("checkbox", { name: /Hiring manager/ }));
    await user.click(screen.getByRole("button", { name: "Create the role" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toMatch(/^\/roles\/[^/]+$/));
    const kept = (mockStore.db.interviews ?? []).map((i) => i.interview_type);
    expect(kept).toEqual(["behavioral", "technical_qa"]);
  });

  it("RF-10: the job category on the check step drives the suggested interviews and is saved", async () => {
    const form = new FormData();
    form.append("text", "Strategy consultant, market entry and profitability cases.");
    await resumesApi.upload(form);
    const user = renderApp("/roles/new");
    await user.click(await screen.findByRole("button", { name: "paste the text" }));
    await user.click(screen.getByRole("textbox", { name: "Job posting text" }));
    await user.paste("Senior engineer, payments. ".repeat(10));
    await user.click(screen.getByRole("button", { name: "Read the posting" }));
    const category = await screen.findByRole("combobox", { name: "Job category" }, { timeout: 4000 });
    expect(within(category).getAllByRole("option")).toHaveLength(12);
    await user.selectOptions(category, "Consulting and strategy");
    await user.click(screen.getByRole("button", { name: "Looks right" }));
    // Network steps get the same headroom as "Read the posting" above, for slow CI runners.
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Case/ })).toBeChecked(), { timeout: 4000 });
    expect(screen.getAllByRole("checkbox")[0]).toHaveAccessibleName(/Case/);
    expect(screen.getByRole("checkbox", { name: /Verbal technical/ })).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Create the role" }));
    // The role page, not the add page: /roles/new also matches /roles/<one segment>.
    await waitFor(() => expect(screen.getByTestId("where").textContent).toMatch(/^\/roles\/(?!new$)[^/]+$/), {
      timeout: 4000,
    });
    const jobId = (screen.getByTestId("where").textContent ?? "").split("/")[2];
    const saved = await jobTargetsApi.get(jobId);
    expect(saved.posting?.role_family).toBe("consulting_strategy");
  });

  it("RF-14: a role in a new job category is labeled Beta; an established one is not", async () => {
    const { job } = await roleWithInterviews("behavioral");
    const stored = mockStore.db.jobs.find((j) => j.id === job.id);
    expect(stored?.posting).toBeTruthy();
    renderApp(`/roles/${job.id}`);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText(/^Beta:/)).not.toBeInTheDocument();
    cleanup();

    if (stored?.posting) stored.posting = { ...stored.posting, role_family: "finance" };
    renderApp(`/roles/${job.id}`);
    expect(await screen.findByText("Beta: Finance")).toHaveAttribute("title", expect.stringMatching(/calibrated/));
  });

  it("TG-4, PP-2: the role page has its interviews, what they'll look for, stories and the context card", async () => {
    const { job, interviews } = await roleWithInterviews("behavioral", "technical_qa");
    mockStore.db.interviewDates = { [job.id]: new Date(Date.now() + 6 * 86_400_000).toISOString().slice(0, 10) };
    renderApp(`/roles/${job.id}`);
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(await screen.findByText(/in 6 days$/)).toBeInTheDocument();
    const ivs = screen.getByRole("region", { name: "Interviews for this role" });
    const links = within(ivs).getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toEqual(interviews.map((i) => `/interviews/${i.id}`));
    expect(within(ivs).getAllByText("Start a take")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "What they'll look for" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Your stories for this role" })).toBeInTheDocument();
    const ctx = screen.getByRole("region", { name: "Know anything about this interview?" });
    expect(within(ctx).getByRole("button", { name: "Add what you know" })).toBeInTheDocument();
    const look = screen.getByRole("region", { name: "What they'll look for" });
    expect(within(look).getByRole("link", { name: "See the full gap report" })).toHaveAttribute("href", `/jobs/${job.id}/gap-report`);
  });

  it("LB-2: a role nothing uses can be deleted from its page, after a confirm", async () => {
    const { job_target: created } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
    const job = await jobTargetsApi.get(created.id);
    const user = renderApp(`/roles/${job.id}`);
    const card = await screen.findByRole("region", { name: "Remove this role" });
    expect(card).toHaveTextContent("Nothing uses this role yet");
    await user.click(within(card).getByRole("button", { name: "Delete role" }));
    expect(within(card).getByText(/can't be undone/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Delete role" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/roles$/));
    expect(mockStore.db.jobs.find((j) => j.id === job.id)?.deleted).toBe(true);
  });

  it("LB-2: a role with a gap report is archived, not deleted", async () => {
    const { job } = await roleWithInterviews("behavioral");
    const user = renderApp(`/roles/${job.id}`);
    const card = await screen.findByRole("region", { name: "Remove this role" });
    await waitFor(() => expect(card).toHaveTextContent("can't be deleted"));
    expect(within(card).queryByRole("button", { name: "Delete role" })).toBeNull();
    await user.click(within(card).getByRole("button", { name: "Archive role" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/roles$/));
    expect(mockStore.db.jobs.find((j) => j.id === job.id)?.archived_at).toBeTruthy();
  });

  it("TG-4: the role page shows the job posting Strova read, closed, with its responsibilities and skills", async () => {
    const { job } = await roleWithInterviews("behavioral");
    const user = userEvent.setup();
    renderApp(`/roles/${job.id}`);
    const card = await screen.findByRole("group", { name: "The job posting" });
    expect(card).not.toHaveAttribute("open");
    expect(card).toHaveTextContent(/\d+ responsibilit(y|ies) · \d+ must-have skills/);
    await user.click(within(card).getByRole("heading", { name: "The job posting" }));
    expect(card).toHaveAttribute("open");
    expect(within(card).getByRole("heading", { name: "What you'll do" })).toBeInTheDocument();
    expect(within(card).getAllByRole("listitem").length).toBeGreaterThan(0);
  });
});

describe("rehearsals", () => {
  it("RH-4: the rehearsals page lists every interview and recommends the next take", async () => {
    const { interviews } = await roleWithInterviews("behavioral", "hiring_manager");
    renderApp("/rehearsals");
    expect(await screen.findByRole("heading", { level: 1, name: "Rehearsals with Strova" })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Strova is interviewing" })[0]).toHaveAttribute("width", "72");
    const hero = await screen.findByRole("region", { name: "Recommended next take" });
    expect(within(hero).getByRole("link")).toHaveAttribute("href", `/interviews/${interviews[0].id}`);
    for (const i of interviews) {
      expect(screen.getAllByRole("link").some((a) => a.getAttribute("href") === `/interviews/${i.id}`)).toBe(true);
    }
  });

  it("RH-3, RD-3: a new interview shows the first-take state; Start creates the take for this interview", async () => {
    const { interviews, job } = await roleWithInterviews("behavioral");
    const user = renderApp(`/interviews/${interviews[0].id}`);
    expect(await screen.findByRole("heading", { level: 1, name: "Behavioral interview" })).toBeInTheDocument();
    const readiness = screen.getByRole("region", { name: "Readiness" });
    expect(readiness).toHaveTextContent("Your readiness appears after your first Realistic take.");
    expect(screen.getByRole("region", { name: "Skill coverage" })).toBeInTheDocument();
    const hero = screen.getByRole("region", { name: "Next take" });
    expect(hero).toHaveTextContent("Take 1");
    expect(hero).toHaveTextContent(/Strova will act as/);
    expect(screen.getByText("No takes yet. Your first take sets your starting readiness.")).toBeInTheDocument();
    await user.click(within(hero).getByRole("button", { name: "Start the first take" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toMatch(/^\/sessions\/.+\/live$/));
    const session = mockStore.db.sessions.at(-1) as SessionRecord;
    expect(session.job_target_id).toBe(job.id);
    expect(session.config.interview_type).toBe("behavioral");
  });

  it("RH-3, PP-4: the settings drawer has difficulty, mode, tone and length, with the paywall rules", async () => {
    const { interviews } = await roleWithInterviews("behavioral");
    const user = renderApp(`/interviews/${interviews[0].id}`);
    await user.click(await screen.findByRole("button", { name: "Change settings" }));
    const drawer = screen.getByTestId("take-settings");
    for (const group of ["Difficulty", "Mode", "Tone", "Length"]) {
      expect(within(drawer).getByRole("group", { name: group })).toBeInTheDocument();
    }
    const mode = within(drawer).getByRole("group", { name: "Mode" });
    expect(within(mode).getAllByRole("button").map((b) => b.textContent)).toEqual(["Realistic", "Practice"]);
    expect(drawer).toHaveTextContent("Practice lets you pause, ask for a hint, or redo an answer. Does not count toward readiness.");
    const length = within(drawer).getByRole("group", { name: "Length" });
    // A free account runs 10-minute takes only.
    expect(within(length).getByRole("button", { name: "30 min" })).toBeDisabled();
    expect(within(length).getByRole("button", { name: "10 min" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(mode).getByRole("button", { name: "Practice" }));
    expect(screen.getByRole("region", { name: "Next take" })).toHaveTextContent("Practice, 10 minutes");
  });

  it("RH-5: the mode labels are Realistic and Practice; a Practice take is stored as coach", async () => {
    const { interviews } = await roleWithInterviews("behavioral");
    const user = renderApp(`/interviews/${interviews[0].id}`);
    await user.click(await screen.findByRole("button", { name: "Change settings" }));
    const mode = within(screen.getByTestId("take-settings")).getByRole("group", { name: "Mode" });
    expect(within(mode).queryByRole("button", { name: /Coach/ })).toBeNull();
    await user.click(within(mode).getByRole("button", { name: "Practice" }));
    await user.click(within(screen.getByRole("region", { name: "Next take" })).getByRole("button", { name: "Start the first take" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toMatch(/^\/sessions\/.+\/live$/));
    expect((mockStore.db.sessions.at(-1) as SessionRecord).config.mode).toBe("coach");
  });
});
