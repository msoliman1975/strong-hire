/**
 * IN-3 "Check your CV": the user fixes the extracted roles before the gap analysis. Runs against
 * the MSW mock of PUT /resumes/{id}.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "../../api/inputs";
import type { Resume } from "../../api/types";
import { AppRoutes, createQueryClient } from "../../App";
import { resume as fixtureResume } from "../../mocks/fixtures";
import { mockStore, server } from "../../mocks/node";
import { toDraft, validateResumeDraft } from "./CheckResumePage";

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

async function seed() {
  signedIn();
  const { job_target: job } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  await jobTargetsApi.get(job.id);
  const form = new FormData();
  form.append("text", "Backend engineer, seven years of Python.");
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  return { job, resume };
}

function renderCheck(jobId: string, resumeId: string) {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/jobs/${jobId}/resume/${resumeId}/check`]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

function recordPutBodies(): { resume: Resume }[] {
  const bodies: { resume: Resume }[] = [];
  server.events.on("request:start", async ({ request }) => {
    if (request.method === "PUT" && /\/api\/resumes\/[^/]+$/.test(request.url)) {
      bodies.push((await request.clone().json()) as { resume: Resume });
    }
  });
  return bodies;
}

describe("validateResumeDraft", () => {
  it("builds the Resume, drops empty achievements and keeps summary, education and certifications", () => {
    const draft = toDraft(fixtureResume);
    draft.roles[0].achievements.push("   ");
    draft.roles[0].end = "";
    draft.skills = "Python, Go, , Python";
    const { errors, resume } = validateResumeDraft(draft, fixtureResume);
    expect(errors).toEqual({});
    expect(resume?.roles[0].achievements).toEqual(fixtureResume.roles[0].achievements);
    expect(resume?.roles[0].end).toBeNull();
    expect(resume?.skills).toEqual(["Python", "Go"]);
    expect(resume?.summary).toBe(fixtureResume.summary);
    expect(resume?.education).toEqual(fixtureResume.education);
    expect(resume?.certifications).toEqual(fixtureResume.certifications);
  });

  it("needs company and title, YYYY or YYYY-MM dates, and an end after the start", () => {
    const draft = toDraft(fixtureResume);
    draft.roles[0].company = " ";
    draft.roles[0].title = "";
    draft.roles[0].start = "March 2021";
    draft.roles[1].start = "2020";
    draft.roles[1].end = "2019-12";
    const { errors, resume } = validateResumeDraft(draft, fixtureResume);
    expect(resume).toBeNull();
    expect(Object.keys(errors).sort()).toEqual(["role-0-company", "role-0-start", "role-0-title", "role-1-end"]);
  });

  it("accepts a year alone and rejects month 13", () => {
    const draft = toDraft(fixtureResume);
    draft.roles[0].start = "2021";
    expect(validateResumeDraft(draft, fixtureResume).errors).toEqual({});
    draft.roles[0].start = "2021-13";
    expect(validateResumeDraft(draft, fixtureResume).errors).toHaveProperty("role-0-start");
  });
});

describe("Check your CV page", () => {
  it("moves an achievement to another job, removes one, confirms and goes to the context step", async () => {
    const { job, resume } = await seed();
    const puts = recordPutBodies();
    const user = renderCheck(job.id, resume.id);
    expect(await screen.findByRole("heading", { name: "Check your CV" })).toBeInTheDocument();
    const first = await screen.findByRole("group", { name: "Software Engineer II at Shoply" });
    expect(within(first).getByLabelText("Company")).toHaveValue("Shoply");

    // The second achievement at Shoply belongs to Invoicely.
    await user.selectOptions(
      within(first).getByRole("combobox", {
        name: "Move achievement 2 at Software Engineer II at Shoply to another job",
      }),
      "Software Engineer at Invoicely",
    );
    const second = screen.getByRole("group", { name: "Software Engineer at Invoicely" });
    expect(within(second).getAllByRole("textbox", { name: /^Achievement \d/ })).toHaveLength(2);
    await user.click(
      within(second).getByRole("button", { name: "Remove achievement 1 at Software Engineer at Invoicely" }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm and continue" }));

    expect(await screen.findByRole("heading", { name: "Add context (optional)" })).toBeInTheDocument();
    expect(puts).toHaveLength(1);
    const sent = puts[0].resume;
    expect(sent.roles[0].achievements).toEqual(["Built the refunds API used by 40,000 merchants"]);
    expect(sent.roles[1].achievements).toEqual(["Led migration of 30 services to PostgreSQL 15 with zero downtime"]);
    expect(sent.education).toEqual(fixtureResume.education);
    expect(mockStore.db.resumes[0].confirmed_at).not.toBeNull();
  });

  it("adds and removes a job and shows field errors before saving", async () => {
    const { job, resume } = await seed();
    const puts = recordPutBodies();
    const user = renderCheck(job.id, resume.id);
    await screen.findByRole("heading", { name: "Check your CV" });
    await user.click(await screen.findByRole("button", { name: "Add a job" }));
    await user.click(screen.getByRole("button", { name: "Confirm and continue" }));
    expect(await screen.findByText("Fix the fields marked in red, then confirm.")).toBeInTheDocument();
    expect(screen.getByText("Enter the company.")).toBeInTheDocument();
    expect(puts).toHaveLength(0);

    const added = screen.getByRole("group", { name: "Job 3" });
    await user.type(within(added).getByLabelText("Company"), "Northwind Labs");
    await user.type(within(added).getByLabelText("Job title"), "Intern");
    await user.type(within(added).getByLabelText("Start (YYYY or YYYY-MM)"), "2017-06");
    await user.type(within(added).getByLabelText("End (YYYY or YYYY-MM, empty if current)"), "2017-09");
    await user.click(screen.getByRole("button", { name: "Remove the job Software Engineer at Invoicely" }));
    await user.click(screen.getByRole("button", { name: "Confirm and continue" }));

    expect(await screen.findByRole("heading", { name: "Add context (optional)" })).toBeInTheDocument();
    const sent = puts[0].resume;
    expect(sent.roles.map((r) => r.company)).toEqual(["Shoply", "Northwind Labs"]);
    expect(sent.roles[1]).toMatchObject({ title: "Intern", start: "2017-06", end: "2017-09", achievements: [] });
  });
});
