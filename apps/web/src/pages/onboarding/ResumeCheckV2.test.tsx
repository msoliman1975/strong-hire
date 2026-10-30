/**
 * IN-3, IN-12: the v2 "Check your resume" page (behind v2_enabled). The CV as cards, the "What we
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
  const { resume, job: task } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  return { job, resume, task };
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
    expect(screen.getByRole("heading", { name: "Check your resume" })).toBeInTheDocument();
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
    expect(await screen.findByRole("heading", { level: 1, name: /Resumes$/i })).toBeInTheDocument();
    expect(puts[0].resume.roles.map((r) => r.company)).toEqual(["Northwind Labs", "Invoicely"]);
  });

  it("IN-3 regression: editing a role updates that role, and never adds one", async () => {
    const { resume } = await seed();
    const puts = recordPutBodies();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });

    await user.click(screen.getByRole("button", { name: "Edit Software Engineer · Invoicely" }));
    const editor = screen.getByRole("group", { name: "Editing · Software Engineer · Invoicely" });
    const title = within(editor).getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Backend Engineer");
    await user.click(within(editor).getByRole("button", { name: "Save role" }));
    expect(screen.getByRole("region", { name: "Backend Engineer · Invoicely" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Software Engineer · Invoicely" })).not.toBeInTheDocument();
    expect(screen.getByText(/Experience · 2 roles/)).toBeInTheDocument();

    // A role added and then cancelled leaves nothing behind.
    await user.click(screen.getByRole("button", { name: "+ Add a role" }));
    await user.click(within(screen.getByRole("group", { name: "Editing · New role" })).getByRole("button", { name: "Cancel" }));
    expect(screen.getByText(/Experience · 2 roles/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Untitled role/ })).not.toBeInTheDocument();

    // Moving an achievement, then cancelling, does not copy it into both roles.
    await user.click(screen.getByRole("button", { name: "Edit Software Engineer II · Shoply" }));
    const shoply = screen.getByRole("group", { name: "Editing · Software Engineer II · Shoply" });
    await user.selectOptions(
      within(shoply).getByRole("combobox", { name: "Move achievement 1 at Software Engineer II · Shoply to another role" }),
      "Backend Engineer at Invoicely",
    );
    await user.click(within(shoply).getByRole("button", { name: "Cancel" }));
    await user.click(
      within(screen.getByRole("group", { name: "Editing · Backend Engineer · Invoicely" })).getByRole("button", { name: "Cancel" }),
    );

    await user.click(screen.getAllByRole("button", { name: "Back to resumes" })[0]);
    expect(await screen.findByRole("heading", { level: 1, name: /Resumes$/i })).toBeInTheDocument();
    expect(puts).toHaveLength(1);
    expect(puts[0].resume.roles.map((r) => `${r.title} · ${r.company}`)).toEqual([
      "Software Engineer II · Shoply",
      "Backend Engineer · Invoicely",
    ]);
    expect(puts[0].resume.roles.map((r) => r.achievements)).toEqual(fixtureResume.roles.map((r) => r.achievements));
  });

  it("IN-3 regression: editing the company of a saved CV opened from Resumes updates that role", async () => {
    await seed();
    mockStore.db.resumes[0].confirmed_at = "2026-10-28T10:00:00Z";
    const puts = recordPutBodies();
    const user = renderAt("/resumes");
    const list = await screen.findByRole("list", { name: "Saved resumes" });
    await user.click(within(list).getAllByRole("link", { name: /^Open breakdown for / })[0]);
    await screen.findByRole("complementary", { name: "What we found" });

    await user.click(screen.getByRole("button", { name: "Edit Software Engineer II · Shoply" }));
    const editor = screen.getByRole("group", { name: "Editing · Software Engineer II · Shoply" });
    const company = within(editor).getByLabelText("Company");
    await user.clear(company);
    await user.type(company, "Shoply Inc");
    await user.click(within(editor).getByRole("button", { name: "Save role" }));
    expect(screen.getByText(/Experience · 2 roles/)).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Back to resumes" })[0]);
    expect(await screen.findByRole("heading", { level: 1, name: /Resumes$/i })).toBeInTheDocument();
    expect(puts[0].resume.roles.map((r) => `${r.title} · ${r.company}`)).toEqual([
      "Software Engineer II · Shoply Inc",
      "Software Engineer · Invoicely",
    ]);

    // Opened again from Resumes and edited again: still two roles.
    await user.click(within(await screen.findByRole("list", { name: "Saved resumes" })).getAllByRole("link", { name: /^Open breakdown for / })[0]);
    await screen.findByRole("complementary", { name: "What we found" });
    await user.click(screen.getByRole("button", { name: "Edit Software Engineer II · Shoply Inc" }));
    const again = screen.getByRole("group", { name: "Editing · Software Engineer II · Shoply Inc" });
    await user.type(within(again).getByLabelText("Title"), " (Payments)");
    await user.click(within(again).getByRole("button", { name: "Save role" }));
    await user.click(screen.getAllByRole("button", { name: "Back to resumes" })[0]);
    await screen.findByRole("heading", { level: 1, name: /Resumes$/i });
    expect(puts[1].resume.roles.map((r) => `${r.title} · ${r.company}`)).toEqual([
      "Software Engineer II (Payments) · Shoply Inc",
      "Software Engineer · Invoicely",
    ]);
  });

  it("IN-12: a section's issue count shows and highlights its issues in the panel", async () => {
    const { resume } = await seed();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    // Another filter first: the click shows every issue again.
    await user.click(within(panel()).getByRole("button", { name: /^Dates/ }));
    expect(within(panel()).queryByText("One achievement on Invoicely")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Show the \d+ issues? for Software Engineer · Invoicely$/ }));
    const card = issueCard("One achievement on Invoicely");
    expect(card).toHaveAttribute("data-highlight", "true");
    expect(card).toHaveAttribute("open");
    expect(issueCard("A skill missing from Skills")).not.toHaveAttribute("data-highlight");

    await user.click(screen.getByRole("button", { name: "Show the 1 issue for Skills" }));
    expect(issueCard("A skill missing from Skills")).toHaveAttribute("data-highlight", "true");
  });

  it("IN-12: What we check sits at the top of the issues column, folded", async () => {
    const { resume } = await seed();
    renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    const checks = within(panel()).getByText("What we check").closest("details")!;
    expect(panel().firstElementChild).toBe(checks);
    expect(checks).not.toHaveAttribute("open");
  });

  it("IN-12: a missing date can be accepted with a reason, and stops counting as an issue", async () => {
    const { resume } = await seed();
    mockStore.db.resumes[0].resume!.roles[1].start = null;
    const user = renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    const card = issueCard("No start date on Invoicely");
    expect(within(card).getByText(/Leaving old dates off on purpose is fine/)).toBeInTheDocument();
    const before = Number(/(\d+) open/.exec(within(panel()).getByText(/open ·/).textContent!)![1]);

    await user.click(within(card).getByRole("button", { name: "Accept: Left out on purpose (age bias)" }));
    expect(within(panel()).queryByText("No start date on Invoicely")).not.toBeInTheDocument();
    expect(within(panel()).getByText(/✓ Accepted: No start date on Invoicely/)).toHaveTextContent(
      "Left out on purpose (age bias)",
    );
    expect(within(panel()).getByText(/open ·/)).toHaveTextContent(`${before - 1} open · 1 accepted`);
    const stored = () => (mockStore.db.resumes[0].accepted_issues ?? []).map((i) => i.key);
    await waitFor(() => expect(stored()).toEqual(["dates.missing-start:invoicely/software-engineer|why=on-purpose"]));

    // Changing the reason replaces the stored key; the issue stays accepted after a reload.
    await user.click(within(panel()).getByRole("button", { name: "Undo accepting No start date on Invoicely" }));
    await waitFor(() => expect(stored()).toEqual([]));
    await user.click(within(issueCard("No start date on Invoicely")).getByRole("button", { name: "Accept: I don't remember" }));
    await waitFor(() => expect(stored()).toEqual(["dates.missing-start:invoicely/software-engineer|why=dont-remember"]));
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
    const { resume, task } = await seed();
    const puts = recordPutBodies();
    // A new upload from the Resumes page brings its reading job.
    const user = renderAt(`/resumes/${resume.id}/check?task=${task?.id ?? ""}`);
    await screen.findByRole("complementary", { name: "What we found" });
    expect(screen.getByRole("status")).toHaveTextContent("We read your resume. Check it, then continue.");
    const next = screen.getAllByRole("button", { name: "Add a job description to practice for" });
    expect(next).toHaveLength(2);
    expect(within(screen.getByRole("region", { name: "Next step" })).getByRole("button", { name: "Back to resumes" })).toBeInTheDocument();
    await user.click(next[1]);
    expect(await screen.findByRole("heading", { level: 1, name: "Add a target role" })).toBeInTheDocument();
    expect(puts).toHaveLength(1);
  });

  it("IN-3: inside a rehearsal the next step is the interview plan, and a confirmed CV has no landing line", async () => {
    const { job, resume } = await seed();
    mockStore.db.resumes[0].confirmed_at = "2026-10-28T10:00:00Z";
    renderAt(`/jobs/${job.id}/resume/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    expect(screen.getAllByRole("button", { name: "Continue to your interview plan" })).toHaveLength(2);
    expect(screen.queryByText("We read your resume. Check it, then continue.")).not.toBeInTheDocument();
  });

  it("IN-3: keeps the v1 form when v2_enabled is off", async () => {
    setFeatureOverrides({ v2_enabled: false });
    const { resume } = await seed();
    renderAt(`/resumes/${resume.id}/check`);
    expect(await screen.findByRole("button", { name: "Confirm and continue" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "What we found" })).not.toBeInTheDocument();
  });
});

describe("v2 coming back to a saved CV", () => {
  const ACCEPTED = { key: "consistency.skills-missing:celery", accepted_at: "2026-10-28T10:00:00Z" };
  const confirmed = () => {
    Object.assign(mockStore.db.resumes[0], { confirmed_at: "2026-10-28T10:00:00Z", accepted_issues: [ACCEPTED] });
  };
  const expectSameBreakdown = async () => {
    await screen.findByRole("complementary", { name: "What we found" });
    expect(within(panel()).getByText("✓ Accepted: A skill missing from Skills")).toBeInTheDocument();
    expect(screen.queryByText("We read your resume. Check it, then continue.")).not.toBeInTheDocument();
    expect(screen.getByTestId("cvc-saved")).toHaveTextContent(/^Last saved Oct 28(, 2026)? · \d+ issues? open$/);
    expect(screen.getAllByRole("button", { name: "Use this resume for an interview" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Back to resumes" })).toHaveLength(2);
  };

  it("IN-12: the Saved CVs row shows its state and opens the same breakdown, accepted issues kept", async () => {
    await seed();
    confirmed();
    const user = renderAt("/resumes");
    const list = await screen.findByRole("list", { name: "Saved resumes" });
    const row = within(list).getAllByRole("listitem")[0];
    expect(row).toHaveTextContent(/Checked Oct 28(, 2026)? · \d+ to fix · 1 accepted · \d+ high/);
    const open = within(row).getByRole("link", { name: /^Open breakdown for / });
    expect(open).toHaveAttribute("href", `/resumes/${mockStore.db.resumes[0].id}/check`);
    await user.click(open);
    await expectSameBreakdown();
  });

  it("IN-12: a click on the row itself opens the breakdown, and Rename stays a rename", async () => {
    await seed();
    const user = renderAt("/resumes");
    const list = await screen.findByRole("list", { name: "Saved resumes" });
    const row = within(list).getAllByRole("listitem")[0];
    expect(row).toHaveTextContent("Not checked yet");
    await user.click(within(row).getByRole("button", { name: /^Rename / }));
    expect(within(row).getByRole("textbox", { name: "New name" })).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Cancel" }));
    await user.click(within(row).getByText(/^added /));
    expect(await screen.findByRole("complementary", { name: "What we found" })).toBeInTheDocument();
  });

  it("IN-12: a deep link with no task loads the saved CV, recomputes the issues and keeps the accepted ones", async () => {
    const { resume } = await seed();
    confirmed();
    renderAt(`/resumes/${resume.id}/check`);
    await expectSameBreakdown();
  });

  it("IN-12: an unchecked CV opened later has no landing line, and says it is not saved yet", async () => {
    const { resume } = await seed();
    const puts = recordPutBodies();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await screen.findByRole("complementary", { name: "What we found" });
    expect(screen.queryByText("We read your resume. Check it, then continue.")).not.toBeInTheDocument();
    expect(screen.getByTestId("cvc-saved")).toHaveTextContent(/Not saved yet · \d+ issues? open/);
    await user.click(screen.getAllByRole("button", { name: "Use this resume for an interview" })[0]);
    expect(await screen.findByRole("heading", { level: 1, name: "Add a target role" })).toBeInTheDocument();
    expect(puts).toHaveLength(1);
  });

  it("IN-12: the Resumes card on Home links each CV to its breakdown", async () => {
    await seed();
    const form = new FormData();
    form.append("text", "Second CV, Python and Go.");
    const { resume: second } = await resumesApi.upload(form);
    await resumesApi.get(second.id);
    confirmed();
    const user = renderAt("/");
    const card = await screen.findByRole("region", { name: "The resume your interviews are measured against." });
    const links = await within(card).findAllByRole("link", { name: /^Open breakdown for / });
    expect(links.map((l) => l.getAttribute("href")).sort()).toEqual(
      mockStore.db.resumes.map((r) => `/resumes/${r.id}/check`).sort(),
    );
    expect(card).toHaveTextContent(/1 accepted/);
    const first = links.find((l) => l.getAttribute("href") === `/resumes/${mockStore.db.resumes[0].id}/check`)!;
    await user.click(first);
    await expectSameBreakdown();
  });
});
