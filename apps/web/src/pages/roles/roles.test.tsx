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
  const { pathname, search } = useLocation();
  return (
    <>
      <span data-testid="where">{pathname}</span>
      <span data-testid="where-search">{search}</span>
    </>
  );
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
      const found = screen.getAllByRole("region").find((s) => within(s).queryByRole("link", { name: /Show details/ })?.getAttribute("href") === `/roles/${job.id}`);
      expect(found).toBeDefined();
      return found as HTMLElement;
    });
    await within(c).findAllByRole("meter");
    expect(within(c).getByText("No date yet")).toBeInTheDocument();
    expect(c).toHaveTextContent("Default resume");
    expect(within(c).getAllByRole("meter")).toHaveLength(2);
    expect(within(c).getAllByText("Not started")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Add a target role" })).toHaveAttribute("href", "/roles/new");
  });

  it("RSD-4: a role card uses the shared shell: tiles for match, interviews and days left, Show details, and no card link", async () => {
    const { job } = await roleWithInterviews("behavioral", "hiring_manager");
    renderApp("/roles");
    const c = await waitFor(() => {
      const found = screen.getAllByRole("region").find((s) => within(s).queryByRole("link", { name: /Show details/ })?.getAttribute("href") === `/roles/${job.id}`);
      expect(found).toBeDefined();
      return found as HTMLElement;
    });
    expect(c.tagName).toBe("SECTION");
    expect(c.closest("a")).toBeNull();
    expect(within(c).getAllByRole("term").map((t) => t.textContent)).toEqual(["match", "interviews", "days left"]);
    const values = within(c).getAllByRole("definition").map((d) => d.textContent);
    expect(values[1]).toBe("2");
    // No interview date yet: days left is unknown.
    expect(values[2]).toBe("—");
    expect(within(c).getAllByRole("link")).toHaveLength(1);
    expect(within(c).getByRole("heading", { level: 2 })).toBeInTheDocument();
    const add = screen.getAllByRole("link").find((a) => a.classList.contains("sx-summary-add"));
    expect(add).toHaveAttribute("href", "/roles/new");
    expect(add).toHaveTextContent("Paste a job posting and Strova suggests the interviews.");
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
    expect(screen.getByText(/Measured against:/)).toHaveTextContent("(default)");
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
    expect(within(category).getAllByRole("option")).toHaveLength(14);
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
    // The role's actions are at the top: the job posting, what you know, and remove.
    const actions = screen.getByRole("group", { name: "Role actions" });
    // Archive, not delete: the role has a gap report (once it has loaded).
    await waitFor(() =>
      expect(within(actions).getAllByRole("button").map((b) => b.textContent)).toEqual(["Job posting", "Add what you know", "Archive role"]),
    );
    const look = screen.getByRole("region", { name: "What they'll look for" });
    expect(within(look).getByRole("link", { name: "See the full gap report" })).toHaveAttribute("href", `/jobs/${job.id}/gap-report`);
  });

  it("LB-2: a role nothing uses can be deleted from its actions, after a confirm", async () => {
    const { job_target: created } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
    const job = await jobTargetsApi.get(created.id);
    const user = renderApp(`/roles/${job.id}`);
    const actions = await screen.findByRole("group", { name: "Role actions" });
    await user.click(within(actions).getByRole("button", { name: "Delete role" }));
    const confirm = screen.getByTestId("remove-role");
    expect(confirm).toHaveAttribute("open");
    expect(confirm).toHaveTextContent("Nothing uses this role yet");
    expect(confirm).toHaveTextContent("can't be undone");
    await user.click(within(confirm).getByRole("button", { name: "Delete role" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/roles$/));
    expect(mockStore.db.jobs.find((j) => j.id === job.id)?.deleted).toBe(true);
  });

  it("LB-2: a role with a gap report is archived, not deleted", async () => {
    const { job } = await roleWithInterviews("behavioral");
    const user = renderApp(`/roles/${job.id}`);
    const actions = await screen.findByRole("group", { name: "Role actions" });
    await waitFor(() => expect(within(actions).getByRole("button", { name: "Archive role" })).toBeInTheDocument());
    expect(within(actions).queryByRole("button", { name: "Delete role" })).toBeNull();
    await user.click(within(actions).getByRole("button", { name: "Archive role" }));
    const confirm = screen.getByTestId("remove-role");
    expect(confirm).toHaveTextContent("can't be deleted");
    await user.click(within(confirm).getByRole("button", { name: "Archive role" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/roles$/));
    expect(mockStore.db.jobs.find((j) => j.id === job.id)?.archived_at).toBeTruthy();
  });

  it("TG-4: Job posting, at the top, opens what Strova read: responsibilities and skills", async () => {
    const { job } = await roleWithInterviews("behavioral");
    const user = renderApp(`/roles/${job.id}`);
    const actions = await screen.findByRole("group", { name: "Role actions" });
    const dialog = screen.getByTestId("posting-dialog");
    expect(dialog).not.toHaveAttribute("open");
    await user.click(within(actions).getByRole("button", { name: "Job posting" }));
    expect(dialog).toHaveAttribute("open");
    expect(dialog).toHaveTextContent(/\d+ responsibilit(y|ies) · \d+ must-have skills/);
    expect(within(dialog).getByRole("heading", { name: "What you'll do" })).toBeInTheDocument();
    expect(within(dialog).getAllByRole("listitem").length).toBeGreaterThan(0);
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(dialog).not.toHaveAttribute("open");
  });
});

describe("a deleted resume (RMAP-5)", () => {
  async function roleOnDeletedResume() {
    const setup = await roleWithInterviews("behavioral", "hiring_manager");
    const form = new FormData();
    form.append("text", "Platform engineer, Kubernetes and Terraform. Ran the on-call rotation for 40 services.");
    const { resume: other } = await resumesApi.upload(form);
    await resumesApi.get(other.id);
    await resumesApi.remove(setup.resumeId);
    return { ...setup, otherId: other.id };
  }

  it("RMAP-5: the Resumes delete dialog names the roles that use the resume", async () => {
    await roleWithInterviews("behavioral");
    const user = renderApp("/resumes");
    const list = await screen.findByRole("list", { name: "Your resumes" });
    const row = await waitFor(() => {
      const found = within(list).getAllByRole("listitem").find((li) => li.textContent?.includes("Used by"));
      expect(found).toBeDefined();
      return found as HTMLElement;
    });
    await user.click(within(row).getByRole("button", { name: /^Delete / }));
    const note = within(row).getByTestId("delete-roles-note");
    expect(note).toHaveTextContent(/uses this resume\. It keeps its takes and report, and asks you to pick another resume\./);
  });

  it("RMAP-5: a role on a deleted resume is flagged, and Use this resume moves its interviews", async () => {
    const { job, interviews, otherId } = await roleOnDeletedResume();

    renderApp("/roles");
    expect(await screen.findByText("Pick a resume for this role")).toBeInTheDocument();
    expect(screen.getByText(/Resume deleted/)).toBeInTheDocument();
    cleanup();

    renderApp(`/interviews/${interviews[0].id}`);
    const gone = await screen.findByTestId("resume-gone");
    expect(within(gone).getByRole("link", { name: "Pick a resume for this role" })).toHaveAttribute("href", `/roles/${job.id}`);
    expect(screen.queryByRole("button", { name: /Start the first take|Retake/ })).not.toBeInTheDocument();
    cleanup();

    const user = renderApp(`/roles/${job.id}`);
    const card = await screen.findByTestId("pick-resume");
    expect(within(card).getByRole("combobox", { name: "Resume for this role" })).toHaveValue(otherId);
    await user.click(within(card).getByRole("button", { name: "Use this resume" }));
    await waitFor(() => expect(screen.queryByTestId("pick-resume")).not.toBeInTheDocument());

    const live = (mockStore.db.interviews ?? []).filter((i) => i.job_target_id === job.id && !i.archived_at);
    expect(live.map((i) => i.resume_id)).toEqual([otherId, otherId]);
    expect(live.map((i) => i.interview_type).sort()).toEqual(["behavioral", "hiring_manager"]);
    const old = (mockStore.db.interviews ?? []).filter((i) => interviews.some((o) => o.id === i.id));
    expect(old.every((i) => i.archived_at)).toBe(true);
  });

  it("RMAP-5: with no resume left, the role offers Add a resume", async () => {
    const { job, resumeId } = await roleWithInterviews("behavioral");
    await resumesApi.remove(resumeId);
    renderApp(`/roles/${job.id}`);
    const card = await screen.findByTestId("pick-resume");
    expect(within(card).getByRole("link", { name: "Add a resume" })).toBeInTheDocument();
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

  it("RMAP-1: the Target role filter narrows the list and the recommended take, and the URL keeps it", async () => {
    const first = await roleWithInterviews("behavioral", "hiring_manager");
    const second = await roleWithInterviews("technical_qa");
    const user = renderApp("/rehearsals");
    const filter = await screen.findByRole("combobox", { name: "Target role" });
    const list = await screen.findByTestId("rehearsal-list");
    const hrefs = () => within(list).getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs()).toHaveLength(3);
    expect(within(filter).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All target roles (3)",
      expect.stringMatching(/\(1\)$/),
      expect.stringMatching(/\(2\)$/),
    ]);

    await user.selectOptions(filter, second.job.id);
    expect(hrefs()).toEqual([`/interviews/${second.interviews[0].id}`]);
    const hero = screen.getByRole("region", { name: "Recommended next take" });
    expect(within(hero).getByRole("link")).toHaveAttribute("href", `/interviews/${second.interviews[0].id}`);
    expect(screen.getByTestId("where-search")).toHaveTextContent(`?role=${second.job.id}`);

    await user.selectOptions(filter, first.job.id);
    expect(hrefs()).toEqual(first.interviews.map((i) => `/interviews/${i.id}`));
    expect(within(screen.getByRole("region", { name: "Recommended next take" })).getByRole("link")).toHaveAttribute(
      "href",
      `/interviews/${first.interviews[0].id}`,
    );

    await user.selectOptions(filter, "");
    expect(hrefs()).toHaveLength(3);
    expect(screen.getByTestId("where-search")).toBeEmptyDOMElement();
    // Both roles are at the same company here, so each row names its role title too.
    const titles = within(list)
      .getAllByRole("link")
      .map((a) => a.querySelector("strong")?.textContent ?? "");
    for (const t of titles) expect(t).toMatch(/^.+ · .+ · .+$/);
  });

  it("RMAP-1: a link with ?role opens filtered; an unknown role shows everything; one role has no filter", async () => {
    const first = await roleWithInterviews("behavioral", "hiring_manager");
    const second = await roleWithInterviews("technical_qa");
    renderApp(`/rehearsals?role=${first.job.id}`);
    expect(await screen.findByRole("combobox", { name: "Target role" })).toHaveValue(first.job.id);
    expect(within(screen.getByTestId("rehearsal-list")).getAllByRole("link")).toHaveLength(2);
    cleanup();

    renderApp("/rehearsals?role=gone");
    expect(await screen.findByRole("combobox", { name: "Target role" })).toHaveValue("");
    expect(within(await screen.findByTestId("rehearsal-list")).getAllByRole("link")).toHaveLength(3);
    cleanup();

    mockStore.db.jobs.find((j) => j.id === second.job.id)!.archived_at = "2026-11-01T10:00:00Z";
    renderApp("/rehearsals");
    expect(within(await screen.findByTestId("rehearsal-list")).getAllByRole("link")).toHaveLength(2);
    expect(screen.queryByRole("combobox", { name: "Target role" })).not.toBeInTheDocument();
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

  it("RP-4, RP-8, D-11: a role-play take picks the call, defaulting by level, and is labeled Beta", async () => {
    const { interviews } = await roleWithInterviews("role_play");
    const user = renderApp(`/interviews/${interviews[0].id}`);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Beta");
    await user.click(await screen.findByRole("button", { name: "Change settings" }));
    const call = within(screen.getByTestId("take-settings")).getByRole("group", { name: "Call" });
    // The profile's target level is senior, so the default call is demo and objections.
    expect(within(call).getByRole("button", { name: "Demo and objections" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(call).getByRole("button", { name: "Cold call" }));
    expect(screen.getByRole("region", { name: "Next take" })).toHaveTextContent("Cold call, Realistic");
    await user.click(within(screen.getByRole("region", { name: "Next take" })).getByRole("button", { name: "Start the first take" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toMatch(/^\/sessions\/.+\/live$/), { timeout: 4000 });
    const config = (mockStore.db.sessions.at(-1) as SessionRecord).config;
    expect(config.interview_type).toBe("role_play");
    expect(config.role_play).toBe("cold_call");
  });

  it("RP-4: other takes send no call", async () => {
    const { interviews } = await roleWithInterviews("behavioral");
    const user = renderApp(`/interviews/${interviews[0].id}`);
    expect(await screen.findByRole("heading", { level: 1 })).not.toHaveTextContent("Beta");
    await user.click(await screen.findByRole("button", { name: "Change settings" }));
    expect(within(screen.getByTestId("take-settings")).queryByRole("group", { name: "Call" })).toBeNull();
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

describe("RSD-4: role tiles", () => {
  it("RSD-4: days left is teal when 0 or more, and '—' otherwise; match is '—' when unknown; singular labels for 1", async () => {
    const { roleStats } = await import("./RolesPage");
    expect(roleStats(82, 3, 5)).toEqual([
      { value: 82, label: "match" },
      { value: 3, label: "interviews" },
      { value: 5, label: "days left", tone: "teal" },
    ]);
    expect(roleStats(null, 1, 0)[2]).toEqual({ value: 0, label: "days left", tone: "teal" });
    expect(roleStats(undefined, 1, 1)).toEqual([
      { value: "—", label: "match" },
      { value: 1, label: "interview" },
      { value: 1, label: "day left", tone: "teal" },
    ]);
    expect(roleStats(70, 0, -2)[2]).toEqual({ value: "—", label: "days left" });
    expect(roleStats(70, 0, null)[2]).toEqual({ value: "—", label: "days left" });
  });
});
