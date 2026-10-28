/**
 * IN-3, IN-12: the v2 "Check your CV" page (behind v2_enabled). The CV as cards, the "What we
 * found" panel, Fix and Accept. Runs against the MSW mock of PUT /resumes/{id}.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "../../api/inputs";
import type { Resume } from "../../api/types";
import { AppRoutes, createQueryClient } from "../../App";
import { resume as fixtureResume } from "../../mocks/fixtures";
import { mockStore, server } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";
import { cvDraftToResume, toCvDraft } from "./ResumeCheckV2";

beforeEach(() => setFeatureOverrides({ v2_enabled: true }));
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

function recordPutBodies(): { resume: Resume }[] {
  const bodies: { resume: Resume }[] = [];
  server.events.on("request:start", async ({ request }) => {
    if (request.method === "PUT" && /\/api\/resumes\/[^/]+$/.test(request.url)) {
      bodies.push((await request.clone().json()) as { resume: Resume });
    }
  });
  return bodies;
}

const panel = () => screen.getByRole("complementary", { name: "What we found" });
const issueCard = (title: string) => within(panel()).getByText(title).closest("details") as HTMLElement;

describe("toCvDraft and cvDraftToResume", () => {
  it("IN-3: keeps every part of the contract and sorts roles newest first", () => {
    const older = { ...fixtureResume, roles: [...fixtureResume.roles].reverse() };
    const draft = toCvDraft(older);
    expect(draft.roles.map((r) => r.company)).toEqual(["Shoply", "Invoicely"]);
    const back = cvDraftToResume(draft);
    expect(back).toEqual({ ...fixtureResume });
  });
});

describe("v2 Check your CV", () => {
  it("IN-3: shows the CV as cards: summary, roles with dates and length, skills and education", async () => {
    const { resume } = await seed();
    renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    expect(screen.getByRole("heading", { name: "Check your CV" })).toBeInTheDocument();
    expect(screen.getByText(fixtureResume.summary!)).toBeInTheDocument();
    const shoply = screen.getByRole("region", { name: "Software Engineer II · Shoply" });
    expect(within(shoply).getByText(/^Mar 2021 to now · /)).toBeInTheDocument();
    expect(within(shoply).getByText("Built the refunds API used by 40,000 merchants")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Software Engineer · Invoicely" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Skills · 5" })).toBeInTheDocument();
    expect(screen.getByText("BSc Computer Science")).toBeInTheDocument();
    // The v1 form is gone.
    expect(screen.queryByRole("button", { name: "Confirm and continue" })).not.toBeInTheDocument();
  });

  it("IN-12: lists what it found; Fix opens the role and focuses the field, and the issue goes when fixed", async () => {
    const { resume } = await seed();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    expect(within(panel()).getByText("One achievement on Invoicely")).toBeInTheDocument();
    expect(within(panel()).getByText("A skill missing from Skills")).toBeInTheDocument();

    await user.click(within(issueCard("One achievement on Invoicely")).getByRole("button", { name: "Add an achievement" }));
    const editor = screen.getByRole("group", { name: "Editing · Software Engineer · Invoicely" });
    const added = within(editor).getByLabelText("Achievement 2 at Software Engineer · Invoicely");
    expect(added).toHaveFocus();
    await user.type(added, "Cut invoice errors 30% for 2,000 customers");
    expect(within(panel()).queryByText("One achievement on Invoicely")).not.toBeInTheDocument();
    await user.click(within(editor).getByRole("button", { name: "Save role" }));
    expect(screen.getByText("Cut invoice errors 30% for 2,000 customers")).toBeInTheDocument();
  });

  it("IN-12: Fix on a date issue highlights the field with a note on the role card", async () => {
    const { resume } = await seed();
    mockStore.db.resumes[0].resume!.roles[1].end = "2021-09"; // overlaps Shoply from 2021-03
    const user = renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    await user.click(within(issueCard("Overlapping roles")).getByRole("button", { name: "Fix the date" }));
    const end = screen.getByLabelText("End (Empty if current)");
    expect(end).toHaveFocus();
    expect(end).toHaveValue("2021-09");
    expect(screen.getByText("Overlaps Shoply by 6 months")).toBeInTheDocument();
    await user.clear(end);
    await user.type(end, "2021-02");
    expect(within(panel()).queryByText("Overlapping roles")).not.toBeInTheDocument();
  });

  it("IN-12: Accept moves an issue to Accepted, the filters count it, and Undo brings it back", async () => {
    const { resume } = await seed();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    const card = issueCard("A skill missing from Skills");
    await user.click(within(card).getByText("A skill missing from Skills"));
    await user.click(within(card).getByRole("button", { name: "Accept as it is" }));
    expect(within(panel()).getByText("✓ Accepted: A skill missing from Skills")).toBeInTheDocument();
    expect(within(panel()).getByRole("button", { name: "Accepted 1" })).toBeInTheDocument();

    await user.click(within(panel()).getByRole("button", { name: "Detail 2" }));
    expect(within(panel()).queryByText("✓ Accepted: A skill missing from Skills")).not.toBeInTheDocument();
    expect(within(panel()).getByText("One achievement on Invoicely")).toBeInTheDocument();

    // Part 2: the key is stored on the resume.
    const stored = () => (mockStore.db.resumes[0].accepted_issues ?? []).map((i) => i.key);
    expect(stored()).toEqual(["consistency.skills-missing:celery"]);

    await user.click(within(panel()).getByRole("button", { name: "Accepted 1" }));
    await user.click(within(panel()).getByRole("button", { name: "Undo accepting A skill missing from Skills" }));
    await waitFor(() => expect(stored()).toEqual([]));
    await user.click(within(panel()).getByRole("button", { name: "All" }));
    expect(within(panel()).getByText("A skill missing from Skills")).toBeInTheDocument();
  });

  it("IN-3: edits the summary and certifications, saves the full contract, then continues to the context step", async () => {
    const { job, resume } = await seed();
    const puts = recordPutBodies();
    const user = renderAt(`/jobs/${job.id}/resume/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });

    await user.click(screen.getByRole("button", { name: "Edit the summary" }));
    const summary = screen.getByRole("textbox", { name: "Summary" });
    await user.clear(summary);
    await user.type(summary, "Backend engineer with 7 years in payments. I led 30 service migrations.");
    await user.click(within(screen.getByRole("region", { name: "Summary and intro" })).getByRole("button", { name: "Save" }));

    await user.click(screen.getByRole("button", { name: "Edit certifications" }));
    await user.type(screen.getByRole("textbox", { name: "Certifications" }), "AWS Solutions Architect");
    await user.click(within(screen.getByRole("region", { name: "Certifications" })).getByRole("button", { name: "Save" }));

    await user.click(screen.getAllByRole("button", { name: "Save draft" })[0]);
    expect(await screen.findByText("Draft saved.")).toBeInTheDocument();
    expect(puts).toHaveLength(1);
    expect(puts[0].resume.summary).toBe("Backend engineer with 7 years in payments. I led 30 service migrations.");
    expect(puts[0].resume.certifications).toEqual(["AWS Solutions Architect"]);
    expect(puts[0].resume.education).toEqual(fixtureResume.education);
    expect(puts[0].resume.roles).toEqual(fixtureResume.roles);

    await user.click(screen.getAllByRole("button", { name: "Continue to your interview plan" })[0]);
    expect(await screen.findByRole("heading", { name: "Add context (optional)" })).toBeInTheDocument();
    expect(puts).toHaveLength(2);
  });

  it("IN-3: adds, reorders and removes roles, and blocks saving an incomplete role", async () => {
    const { resume } = await seed();
    const puts = recordPutBodies();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });

    await user.click(screen.getByRole("button", { name: "+ Add a role" }));
    const added = screen.getByRole("group", { name: "Editing · New role" });
    await user.click(within(added).getByRole("button", { name: "Save role" }));
    expect(within(added).getByText("Enter the company.")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Back to resumes" })[0]);
    expect(await screen.findByText("Fix the fields marked in red, then continue.")).toBeInTheDocument();
    expect(puts).toHaveLength(0);

    await user.type(within(added).getByLabelText("Title"), "Intern");
    await user.type(within(added).getByLabelText("Company"), "Northwind Labs");
    await user.type(within(added).getByLabelText("Start (YYYY or YYYY-MM)"), "2017-06");
    await user.type(within(added).getByLabelText("End (Empty if current)"), "2017-09");
    await user.click(within(added).getByRole("button", { name: "Move Intern · Northwind Labs up" }));
    await user.click(within(added).getByRole("button", { name: "Save role" }));

    await user.click(screen.getByRole("button", { name: "Edit Software Engineer II · Shoply" }));
    await user.click(screen.getByRole("button", { name: "Remove the role Software Engineer II · Shoply" }));

    await user.click(screen.getAllByRole("button", { name: "Back to resumes" })[1]);
    expect(await screen.findByRole("heading", { name: "Resumes" })).toBeInTheDocument();
    expect(puts[0].resume.roles.map((r) => r.company)).toEqual(["Northwind Labs", "Invoicely"]);
  });

  it("IN-12: issues accepted earlier stay accepted when the page opens again", async () => {
    const { resume } = await seed();
    mockStore.db.resumes[0].accepted_issues = [
      { key: "consistency.skills-missing:celery", accepted_at: "2026-10-28T10:00:00Z" },
    ];
    renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    expect(within(panel()).getByText("✓ Accepted: A skill missing from Skills")).toBeInTheDocument();
    expect(within(panel()).getByText(/1 accepted/)).toBeInTheDocument();
  });

  it("IN-3: a new CV says where the user is, and ends in one next step, at the top and the bottom", async () => {
    const { resume } = await seed();
    const puts = recordPutBodies();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    expect(screen.getByRole("status")).toHaveTextContent("We read your CV. Check it, then continue.");
    const next = screen.getAllByRole("button", { name: "Add a job description to practice for" });
    expect(next).toHaveLength(2);
    expect(within(screen.getByRole("region", { name: "Next step" })).getByRole("button", { name: "Back to resumes" })).toBeInTheDocument();
    await user.click(next[1]);
    expect(await screen.findByRole("heading", { name: "Add a job description" })).toBeInTheDocument();
    expect(puts).toHaveLength(1);
  });

  it("IN-3: inside a rehearsal the next step is the interview plan, and a confirmed CV has no landing line", async () => {
    const { job, resume } = await seed();
    mockStore.db.resumes[0].confirmed_at = "2026-10-28T10:00:00Z";
    renderAt(`/jobs/${job.id}/resume/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    expect(screen.getAllByRole("button", { name: "Continue to your interview plan" })).toHaveLength(2);
    expect(screen.queryByText("We read your CV. Check it, then continue.")).not.toBeInTheDocument();
  });

  it("IN-3: keeps the v1 form when v2_enabled is off", async () => {
    setFeatureOverrides({ v2_enabled: false });
    const { resume } = await seed();
    renderAt(`/resumes/${resume.id}/check`);
    expect(await screen.findByRole("button", { name: "Confirm and continue" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "What we found" })).not.toBeInTheDocument();
  });
});
