/**
 * R1: saved job descriptions and CVs (pick, "saved before" offer, rename, delete) and the
 * Reports page, against the MSW mocks of the real endpoints.
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

/**
 * A saved, read job; a saved CV named "Ana CV"; a ready gap report; one finished interview.
 * The CV is pasted text: in Node, MSW cannot read a jsdom File from a multipart body.
 */
async function seed() {
  signedIn();
  const { job_target: job } = await jobTargetsApi.create({ text: POSTING });
  await jobTargetsApi.get(job.id);
  const form = new FormData();
  form.append("text", CV_TEXT);
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  await resumesApi.rename(resume.id, "Ana CV");
  const gap = await gapApi.start(job.id, { resume_id: resume.id });
  await gapApi.get(job.id);
  mockStore.db.gaps[job.id].updated_at = "2026-10-02T10:00:00Z";
  mockStore.db.sessions.push({
    id: "00000000-0000-4000-8000-00000000d001",
    job_target_id: job.id,
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

describe("R1 library in the Add a job flow", () => {
  it("lists saved jobs by name; picking one goes to the resume step without reading it again", async () => {
    const { job } = await seed();
    const user = renderAt("/jobs/new");
    const saved = await screen.findByRole("region", { name: "Use a job you saved" });
    expect(within(saved).getByText(JOB_NAME)).toBeInTheDocument();
    await user.click(within(saved).getByRole("button", { name: "Use this job" }));
    expect(await screen.findByRole("heading", { name: "Add your resume" })).toBeInTheDocument();
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
    expect(await screen.findByText(`You saved this job before as ${JOB_NAME}. Use it?`)).toBeInTheDocument();
    expect(mockStore.db.jobs).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Read it again as a new job" }));
    await waitFor(() => expect(mockStore.db.jobs).toHaveLength(2));
  });

  it("uses the saved job from the offer", async () => {
    await seed();
    const user = renderAt("/jobs/new");
    await user.click(await screen.findByLabelText("Or paste the job posting text"));
    await user.paste(POSTING);
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    await user.click(await screen.findByRole("button", { name: "Use the saved job" }));
    expect(await screen.findByRole("heading", { name: "Add your resume" })).toBeInTheDocument();
    expect(mockStore.db.jobs).toHaveLength(1);
  });

  it("a new posting is read at once, with no offer", async () => {
    signedIn();
    const user = renderAt("/jobs/new");
    await user.click(await screen.findByLabelText("Or paste the job posting text"));
    await user.paste(POSTING);
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    await waitFor(() => expect(mockStore.db.jobs).toHaveLength(1));
    expect(screen.queryByText(/You saved this job before/)).not.toBeInTheDocument();
  });

  it("lists saved CVs by name and offers the saved CV for the same content", async () => {
    const { job, resume } = await seed();
    const user = renderAt(`/jobs/${job.id}/resume`);
    const saved = await screen.findByRole("region", { name: "Use a resume you saved" });
    expect(within(saved).getByText("Ana CV")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Or paste your resume text"));
    await user.paste(`  ${CV_TEXT}
`);
    await user.click(screen.getByRole("button", { name: "Upload resume" }));
    expect(await screen.findByText("You saved this CV before as Ana CV. Use it?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use the saved CV" }));
    // The saved CV was never confirmed, so the user checks it first.
    expect(await screen.findByRole("heading", { name: "Check your CV" })).toBeInTheDocument();
    expect(mockStore.db.resumes).toHaveLength(1);
    expect(mockStore.db.resumes[0].id).toBe(resume.id);
  });

  it("a saved CV that the user confirmed before goes straight to the context step", async () => {
    const { job, resume } = await seed();
    const parsed = (await resumesApi.get(resume.id)).resume;
    if (!parsed) throw new Error("the seeded CV is not extracted");
    await resumesApi.update(resume.id, parsed);
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

describe("R1 saved jobs and CVs on the Account page", () => {
  it("renames a saved job and rejects an empty name", async () => {
    await seed();
    const user = renderAt("/account");
    const jobs = await screen.findByRole("region", { name: "Saved jobs" });
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

  it("deletes a CV after a confirmation that says reports are kept", async () => {
    const { resume } = await seed();
    const user = renderAt("/account");
    const cvs = await screen.findByRole("region", { name: "Saved CVs" });
    await user.click(await within(cvs).findByRole("button", { name: "Delete Ana CV" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this CV?" });
    expect(dialog).toHaveTextContent("Your reports, interviews and progress are kept.");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(cvs).findByText("You have no saved CVs.")).toBeInTheDocument();
    expect(mockStore.db.resumes.find((r) => r.id === resume.id)?.deleted).toBe(true);
  });

  it("keeps a job when the user cancels the delete", async () => {
    await seed();
    const user = renderAt("/account");
    const jobs = await screen.findByRole("region", { name: "Saved jobs" });
    await user.click(await within(jobs).findByRole("button", { name: `Delete ${JOB_NAME}` }));
    await user.click(within(screen.getByRole("dialog", { name: "Delete this job?" })).getByRole("button", { name: "Keep it" }));
    expect(mockStore.db.jobs[0].deleted).toBe(false);
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
    expect(within(rows[0]).getByRole("link")).toHaveAttribute("href", "/sessions/00000000-0000-4000-8000-00000000d001/debrief");

    await user.selectOptions(screen.getByLabelText("Type"), "gap_report");
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Reports" })).getAllByRole("listitem")).toHaveLength(1));

    await user.selectOptions(screen.getByLabelText("Type"), "");
    await user.selectOptions(screen.getByLabelText("Job"), other.id);
    expect(await screen.findByText("No reports yet.")).toBeInTheDocument();
  });

  it("shows JD deleted and CV deleted, and the old report still opens", async () => {
    const { job, resume, gap } = await seed();
    await resumesApi.remove(resume.id);
    await jobTargetsApi.remove(job.id);
    const user = renderAt("/reports");
    const list = await screen.findByRole("list", { name: "Reports" });
    expect(within(list).getAllByText(/JD deleted/)).toHaveLength(2);
    expect(within(list).getByText(/CV deleted/)).toBeInTheDocument();

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
