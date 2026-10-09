/**
 * R1: saved job descriptions and CVs (pick, "saved before" offer, rename, delete), the Reports
 * page, LB-1 (Resumes page), LB-2 (Job descriptions page, archive) and PR-3 (rehearsal pairs),
 * against the MSW mocks of the real endpoints.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { gapApi } from "../api/gap";
import { jobTargetsApi, resumesApi, sha256Hex } from "../api/inputs";
import { AppRoutes, createQueryClient } from "../App";
import { mockStore } from "../mocks/node";

const POSTING = "Senior Software Engineer at Stripe. Payments reliability, Python, Go. ".repeat(4);
const JOB_NAME = "Senior Software Engineer, Payments Reliability at Stripe";
const CV_TEXT = "Ana Lopez. Backend engineer, seven years of Python.";

function signedIn(email = "ana@example.com") {
  mockStore.db.users[email] = {
    id: "00000000-0000-4000-8000-0000000000a1",
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email,
    auth_provider: "dev",
    training_consent: false,
    is_admin: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
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

async function pastedCv() {
  const form = new FormData();
  form.append("text", CV_TEXT);
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  return resume;
}

/** Confirm a CV on "Check your CV" without the page: the API marks it confirmed. */
async function confirmCv(resumeId: string) {
  const parsed = (await resumesApi.get(resumeId)).resume;
  if (!parsed) throw new Error("the CV is not extracted");
  await resumesApi.update(resumeId, parsed);
}

/**
 * A saved, read job; a saved CV named "Ana CV"; a ready gap report; one finished interview.
 * The CV is pasted text: in Node, MSW cannot read a jsdom File from a multipart body.
 */
async function seed() {
  signedIn();
  const { job_target: job } = await jobTargetsApi.create({ text: POSTING });
  await jobTargetsApi.get(job.id);
  const resume = await pastedCv();
  await resumesApi.rename(resume.id, "Ana CV");
  const gap = await gapApi.start(job.id, { resume_id: resume.id });
  await gapApi.get(job.id);
  mockStore.db.gaps[job.id].updated_at = "2026-10-02T10:00:00Z";
  mockStore.db.sessions.push({
    id: "00000000-0000-4000-8000-00000000d001",
    job_target_id: job.id,
    resume_id: resume.id,
    config: { interview_type: "behavioral", difficulty: "realistic", mode: "realistic", duration_min: 10, level: "senior" },
    channel: "voice",
    brief_ready: true,
    status: "completed",
    started_at: "2026-10-03T10:00:00Z",
    ended_at: "2026-10-03T10:10:00Z",
    minutes_billed: 10,
    failure_reason: null,
  });
  return { job, resume, gap };
}

describe("R1 library in the Add a job description flow", () => {
  it("lists saved jobs by name; picking one goes to the resume step without reading it again", async () => {
    const { job } = await seed();
    const user = renderAt("/jobs/new");
    const saved = await screen.findByRole("region", { name: "Use a job description you saved" });
    expect(within(saved).getByText(JOB_NAME)).toBeInTheDocument();
    await user.click(within(saved).getByRole("button", { name: "Use this job description" }));
    expect(await screen.findByRole("heading", { name: "Choose a resume" })).toBeInTheDocument();
    expect(mockStore.db.jobs).toHaveLength(1);
    expect(mockStore.db.jobs[0].id).toBe(job.id);
  });

  it("offers the saved job when the pasted text matches; the user can still read it again", async () => {
    await seed();
    const user = renderAt("/jobs/new");
    const text = await screen.findByLabelText("Or paste the job posting text");
    await user.click(text);
    await user.paste(`  ${POSTING.toUpperCase()}  `);
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    expect(
      await screen.findByText(`You saved this job description before as ${JOB_NAME}. Use it?`),
    ).toBeInTheDocument();
    expect(mockStore.db.jobs).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Read it again as a new job description" }));
    await waitFor(() => expect(mockStore.db.jobs).toHaveLength(2));
  });

  it("uses the saved job from the offer", async () => {
    await seed();
    const user = renderAt("/jobs/new");
    await user.click(await screen.findByLabelText("Or paste the job posting text"));
    await user.paste(POSTING);
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    await user.click(await screen.findByRole("button", { name: "Use the saved job description" }));
    expect(await screen.findByRole("heading", { name: "Choose a resume" })).toBeInTheDocument();
    expect(mockStore.db.jobs).toHaveLength(1);
  });

  it("a new posting is read at once, with no offer", async () => {
    signedIn();
    const user = renderAt("/jobs/new");
    await user.click(await screen.findByLabelText("Or paste the job posting text"));
    await user.paste(POSTING);
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    await waitFor(() => expect(mockStore.db.jobs).toHaveLength(1));
    expect(screen.queryByText(/You saved this job description before/)).not.toBeInTheDocument();
  });

  it("lists saved CVs by name and offers the saved CV for the same content", async () => {
    const { job, resume } = await seed();
    const user = renderAt(`/jobs/${job.id}/resume`);
    const saved = await screen.findByRole("region", { name: "Use a resume you saved" });
    expect(within(saved).getByText("Ana CV")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Or paste your resume text"));
    await user.paste(`  ${CV_TEXT}\n`);
    await user.click(screen.getByRole("button", { name: "Upload resume" }));
    expect(await screen.findByText("You saved this CV before as Ana CV. Use it?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use the saved CV" }));
    // The saved CV was never confirmed, so the user checks it first.
    expect(await screen.findByRole("heading", { name: "Check your CV" })).toBeInTheDocument();
    expect(mockStore.db.resumes).toHaveLength(1);
    expect(mockStore.db.resumes[0].id).toBe(resume.id);
  });

  it("a confirmed CV with no report for this job goes on to the context step", async () => {
    signedIn();
    const { job_target: job } = await jobTargetsApi.create({ text: POSTING });
    await jobTargetsApi.get(job.id);
    const resume = await pastedCv();
    await confirmCv(resume.id);
    const user = renderAt(`/jobs/${job.id}/resume`);
    const saved = await screen.findByRole("region", { name: "Use a resume you saved" });
    await user.click(within(saved).getByRole("button", { name: "Use this resume" }));
    expect(await screen.findByRole("heading", { name: "Add context (optional)" })).toBeInTheDocument();
  });

  it("picking the same job and CV again reuses the ready gap report", async () => {
    const { job, resume, gap } = await seed();
    const user = renderAt(`/jobs/${job.id}/context?resume=${resume.id}`);
    await user.click(await screen.findByRole("button", { name: "Skip this step" }));
    expect(await screen.findByTestId("match-score")).toBeInTheDocument();
    expect(mockStore.db.gaps[job.id].id).toBe(gap.id);
  });

  it("the browser hash matches the API's SHA-256", async () => {
    expect(await sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});

describe("PR-3 interview rehearsals: one job and CV pair", () => {
  it("a CV rehearsed before shows the earlier reports and verdicts, then starts a session with it", async () => {
    const { resume } = await seed();
    await confirmCv(resume.id);

    const user = renderAt("/");
    expect(await screen.findByRole("heading", { name: "Interview rehearsals" })).toBeInTheDocument();
    await user.click(await screen.findByRole("link", { name: /^Rehearse/ }));
    const saved = await screen.findByRole("region", { name: "Use a resume you saved" });
    await user.click(within(saved).getByRole("button", { name: "Use this resume" }));

    expect(await screen.findByRole("heading", { name: `Rehearse for ${JOB_NAME}` })).toBeInTheDocument();
    const stand = screen.getByRole("region", { name: "Where you stand" });
    expect(stand).toHaveTextContent("Latest hire signal");
    expect(within(stand).getByText("Scored interviews").nextElementSibling).toHaveTextContent("1");
    const history = screen.getByRole("region", { name: "Earlier reports for this job and CV" });
    expect(within(history).getAllByRole("listitem")).toHaveLength(2);
    expect(await screen.findByRole("region", { name: "Gaps to work on" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Start a session" }));
    await user.click(await screen.findByRole("button", { name: "Start interview" }));
    await waitFor(() => expect(mockStore.db.sessions).toHaveLength(2));
    expect(mockStore.db.sessions[1].resume_id).toBe(resume.id);
  });
});

describe("LB-1 Resumes page", () => {
  it("adds a CV, checks it, and lists it", async () => {
    signedIn();
    const user = renderAt("/resumes");
    expect(await screen.findByRole("heading", { name: "Resumes" })).toBeInTheDocument();
    expect(await screen.findByText("You have no saved CVs.")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Or paste your resume text"));
    await user.paste(CV_TEXT);
    await user.click(screen.getByRole("button", { name: "Upload resume" }));
    expect(await screen.findByRole("heading", { name: "Check your CV" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Confirm and continue" }, { timeout: 4000 }));
    expect(await screen.findByRole("heading", { name: "Resumes" })).toBeInTheDocument();
    const cvs = await screen.findByRole("region", { name: "Saved CVs" });
    expect(await within(cvs).findAllByRole("listitem")).toHaveLength(1);
    expect(mockStore.db.resumes[0].confirmed_at).not.toBeNull();
  });

  it("deletes a CV after a confirmation that says reports are kept", async () => {
    const { resume } = await seed();
    const user = renderAt("/resumes");
    const cvs = await screen.findByRole("region", { name: "Saved CVs" });
    await user.click(await within(cvs).findByRole("button", { name: "Delete Ana CV" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this CV?" });
    expect(dialog).toHaveTextContent("Your reports, interviews and progress are kept.");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(cvs).findByText("You have no saved CVs.")).toBeInTheDocument();
    expect(mockStore.db.resumes.find((r) => r.id === resume.id)?.deleted).toBe(true);
  });

  it("Resumes is in the main menu, and the Account page no longer lists CVs", async () => {
    await seed();
    renderAt("/account");
    expect(await screen.findByRole("heading", { name: "Account" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Saved CVs" })).not.toBeInTheDocument();
    const menu = screen.getByRole("navigation", { name: "Main" });
    expect(within(menu).getByRole("link", { name: "Resumes" })).toHaveAttribute("href", "/resumes");
    expect(within(menu).getByRole("link", { name: "Job descriptions" })).toHaveAttribute("href", "/jobs");
  });
});

describe("LB-2 Job descriptions page", () => {
  it("renames a saved job and rejects an empty name", async () => {
    await seed();
    const user = renderAt("/jobs");
    const jobs = await screen.findByRole("region", { name: "Saved job descriptions" });
    await user.click(await within(jobs).findByRole("button", { name: `Rename ${JOB_NAME}` }));
    const input = within(jobs).getByLabelText("New name");
    await user.clear(input);
    await user.click(within(jobs).getByRole("button", { name: "Save name" }));
    expect(within(jobs).getByRole("alert")).toHaveTextContent("Enter a name.");
    await user.type(input, "  Stripe payments  ");
    await user.click(within(jobs).getByRole("button", { name: "Save name" }));
    expect(await within(jobs).findByText("Stripe payments")).toBeInTheDocument();
    expect(mockStore.db.jobs[0].name).toBe("Stripe payments");
  });

  it("a job with reports is archived, not deleted; Show archived lists it and Restore brings it back", async () => {
    await seed();
    const user = renderAt("/jobs");
    const jobs = await screen.findByRole("region", { name: "Saved job descriptions" });
    const archive = await within(jobs).findByRole("button", { name: `Archive ${JOB_NAME}` });
    expect(within(jobs).queryByRole("button", { name: `Delete ${JOB_NAME}` })).not.toBeInTheDocument();
    await user.click(archive);
    expect(await within(jobs).findByText(/You have no saved job descriptions/)).toBeInTheDocument();
    expect(mockStore.db.jobs[0].archived_at).not.toBeNull();

    await user.click(within(jobs).getByLabelText("Show archived"));
    expect(await within(jobs).findByText("Archived")).toBeInTheDocument();
    await user.click(within(jobs).getByRole("button", { name: `Restore ${JOB_NAME}` }));
    await waitFor(() => expect(mockStore.db.jobs[0].archived_at).toBeNull());
    expect(await within(jobs).findByRole("button", { name: `Archive ${JOB_NAME}` })).toBeInTheDocument();
  });

  it("deletes a job with no reports; Keep it cancels", async () => {
    signedIn();
    const { job_target: job } = await jobTargetsApi.create({ text: POSTING });
    await jobTargetsApi.get(job.id);
    const user = renderAt("/jobs");
    const jobs = await screen.findByRole("region", { name: "Saved job descriptions" });
    await user.click(await within(jobs).findByRole("button", { name: `Delete ${JOB_NAME}` }));
    const dialog = screen.getByRole("dialog", { name: "Delete this job description?" });
    await user.click(within(dialog).getByRole("button", { name: "Keep it" }));
    expect(mockStore.db.jobs[0].deleted).toBe(false);
    await user.click(within(jobs).getByRole("button", { name: `Delete ${JOB_NAME}` }));
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockStore.db.jobs[0].deleted).toBe(true));
  });

  it("Add a job description from this page comes back here after the details are saved", async () => {
    signedIn();
    const user = renderAt("/jobs");
    await user.click(await screen.findByRole("link", { name: "Add a job description" }));
    expect(await screen.findByRole("heading", { name: "Add a job description" })).toBeInTheDocument();
    await user.click(screen.getByLabelText("Or paste the job posting text"));
    await user.paste(POSTING);
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    await user.click(await screen.findByRole("button", { name: "Save and continue" }, { timeout: 4000 }));
    expect(await screen.findByRole("heading", { name: "Job descriptions" })).toBeInTheDocument();
  });
});

describe("R1 Reports page", () => {
  it("lists gap reports and debriefs newest first, with filters by type and by job", async () => {
    const { job, gap } = await seed();
    const { job_target: other } = await jobTargetsApi.create({ text: "Another job. ".repeat(20) });
    const user = renderAt("/reports");
    expect(await screen.findByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports");
    const list = await screen.findByRole("list", { name: "Reports" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(`Interview debrief: ${JOB_NAME}`);
    expect(rows[1]).toHaveTextContent(`Gap report: ${JOB_NAME}`);
    expect(rows[1]).toHaveTextContent("Ana CV");
    expect(within(rows[1]).getByRole("link")).toHaveAttribute("href", `/jobs/${job.id}/gap?report=${gap.id}`);
    expect(within(rows[0]).getByRole("link")).toHaveAttribute(
      "href",
      "/sessions/00000000-0000-4000-8000-00000000d001/debrief",
    );

    await user.selectOptions(screen.getByLabelText("Type"), "gap_report");
    await waitFor(() =>
      expect(within(screen.getByRole("list", { name: "Reports" })).getAllByRole("listitem")).toHaveLength(1),
    );

    await user.selectOptions(screen.getByLabelText("Type"), "");
    await user.selectOptions(screen.getByLabelText("Job"), other.id);
    expect(await screen.findByText("No reports yet.")).toBeInTheDocument();
  });

  it("shows JD deleted and CV deleted, and the old report still opens", async () => {
    const { job, resume, gap } = await seed();
    await resumesApi.remove(resume.id);
    // A job deleted before LB-2. A job with reports can no longer be deleted, only archived.
    Object.assign(mockStore.db.jobs[0], { deleted: true, name: null, posting: null, source_url: null });
    const user = renderAt("/reports");
    const list = await screen.findByRole("list", { name: "Reports" });
    expect(within(list).getAllByText(/JD deleted/)).toHaveLength(2);
    expect(within(list).getAllByText(/CV deleted/).length).toBeGreaterThan(0);

    await user.click(within(list).getByRole("link", { name: "Gap report: JD deleted" }));
    expect(await screen.findByTestId("match-score")).toBeInTheDocument();
    expect(screen.getByText(/CV: CV deleted/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Start the recommended session" })).not.toBeInTheDocument();
    expect(mockStore.db.gaps[job.id].id).toBe(gap.id);
  });

  it("the gap page lists the job's own reports", async () => {
    const { job } = await seed();
    renderAt(`/jobs/${job.id}/gap`);
    const section = await screen.findByRole("region", { name: "Reports for this job" });
    expect(await within(section).findByText("Gap report")).toBeInTheDocument();
    expect(within(section).getByText("Interview debrief")).toBeInTheDocument();
  });
});
