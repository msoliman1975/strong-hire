/**
 * IN-3, IN-12, RSD-7 to RSD-10: the v2 "Check your resume" page (behind v2_enabled). The guided
 * steps: the career journey (the resume as cards), Strova's findings one at a time with the fix in
 * place, Accept and its reasons. Runs against the MSW mock of PUT /resumes/{id}.
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

/** The page is ready when its step list shows. */
const ready = () => screen.findByRole("navigation", { name: "Steps" });
/** Step 2, Strova's findings. */
const findingsView = () => screen.getByTestId("findings-step");
/** The finding in view. */
const finding = () => within(findingsView()).getByRole("article");
/** Opens a finding by its title, from "Next findings" when it is not the one in view. */
async function openFinding(user: ReturnType<typeof userEvent.setup>, title: string) {
  if (within(finding()).queryByRole("heading", { name: title })) return finding();
  await user.click(within(within(findingsView()).getByRole("list", { name: "Next findings" })).getByRole("button", { name: new RegExp(title) }));
  expect(within(finding()).getByRole("heading", { name: title })).toBeInTheDocument();
  return finding();
}
/** RSD-14: opens the "Findings you accepted" drawer from the step list footer. */
async function acceptedDrawer(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /^Findings you accepted · \d+ ›$/ }));
  return screen.getByRole("dialog", { name: /^Findings you accepted/ });
}
/** The open count on the findings step. */
const openCount = () => Number(screen.getByRole("button", { name: /Strova's findings/ }).querySelector(".cvc-step__num")?.textContent);

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
    renderAt(`/resumes/${resume.id}/check?step=journey`);
    await ready();
    expect(screen.getByRole("heading", { level: 1, name: mockStore.db.resumes[0].name ?? "" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Your career journey" })).toBeInTheDocument();
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

  it("IN-12, RSD-10: lists what it found, one at a time; the fix in place saves and the next finding shows", async () => {
    const { resume } = await seed();
    const puts = recordPutBodies();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    const before = openCount();
    const next = within(findingsView()).getByRole("list", { name: "Next findings" });
    expect(within(next).getByRole("button", { name: /A skill missing from Skills/ })).toBeInTheDocument();

    const card = await openFinding(user, "One achievement on Invoicely");
    const box = within(card).getByText("Strova recommends").parentElement as HTMLElement;
    await user.type(within(box).getByLabelText("A new achievement at Invoicely"), "Cut invoice errors 30% for 2,000 customers");
    await user.click(within(box).getByRole("button", { name: "Save achievement" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0].resume.roles[1].achievements).toContain("Cut invoice errors 30% for 2,000 customers");
    await waitFor(() => expect(within(findingsView()).queryByRole("heading", { name: "One achievement on Invoicely" })).not.toBeInTheDocument());
    expect(openCount()).toBe(before - 1);
    // The next finding takes its place.
    expect(within(finding()).getByTestId("finding-position")).toHaveTextContent(/^Finding \d+ of \d+ · (high|medium|low)$/);
  });

  it("IN-12, RSD-10: a date finding shows the date fields of the roles involved, in place", async () => {
    const { resume } = await seed();
    mockStore.db.resumes[0].resume!.roles[1].end = "2021-09"; // overlaps Shoply from 2021-03
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    const card = await openFinding(user, "Overlapping roles");
    const end = within(card).getByLabelText("Invoicely ended");
    expect(end).toHaveValue("2021-09");
    expect(within(card).getByLabelText("Shoply started")).toHaveValue("2021-03");
    await user.clear(end);
    await user.type(end, "2021-02");
    await user.click(within(card).getByRole("button", { name: "Save dates" }));
    await waitFor(() => expect(within(findingsView()).queryByRole("heading", { name: "Overlapping roles" })).not.toBeInTheDocument());
    expect(within(findingsView()).queryByRole("button", { name: /Overlapping roles/ })).not.toBeInTheDocument();
  });

  it("IN-12: a finding with no fix in place opens its field on the journey, with a note on the role", async () => {
    const { resume } = await seed();
    mockStore.db.resumes[0].resume!.roles[1].end = "2021-09";
    const user = renderAt(`/resumes/${resume.id}/check?step=journey`);
    await ready();
    await user.click(screen.getByRole("button", { name: "Edit Software Engineer · Invoicely" }));
    expect(screen.getByText("Overlaps Shoply by 6 months")).toBeInTheDocument();
  });

  it("IN-12: Accept moves a finding to the accepted list, and Undo brings it back", async () => {
    const { resume } = await seed();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    const before = openCount();
    const card = await openFinding(user, "A skill missing from Skills");
    await user.click(within(card).getByRole("button", { name: "Accept as it is" }));
    const list = await acceptedDrawer(user);
    expect(list).toHaveAccessibleName("Findings you accepted · 1");
    expect(within(list).getByText("✓ Accepted: A skill missing from Skills")).toBeInTheDocument();
    expect(openCount()).toBe(before - 1);
    expect(within(findingsView()).queryByRole("heading", { name: "A skill missing from Skills" })).not.toBeInTheDocument();

    // Part 2: the key is stored on the resume.
    const stored = () => (mockStore.db.resumes[0].accepted_issues ?? []).map((i) => i.key);
    expect(stored()).toEqual(["consistency.skills-missing:celery"]);

    await user.click(within(list).getByRole("button", { name: "Undo accepting A skill missing from Skills" }));
    await waitFor(() => expect(stored()).toEqual([]));
    expect(openCount()).toBe(before);
  });

  it("IN-3: edits the summary and certifications, saves the full contract, then continues to the context step", async () => {
    const { job, resume } = await seed();
    const puts = recordPutBodies();
    const user = renderAt(`/jobs/${job.id}/resume/${resume.id}/check`);
    await ready();

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
    const user = renderAt(`/resumes/${resume.id}/check?step=journey`);
    await ready();

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

    await user.click(screen.getByRole("button", { name: "Save and go back to resumes" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Resumes$/i })).toBeInTheDocument();
    expect(puts[0].resume.roles.map((r) => r.company)).toEqual(["Northwind Labs", "Invoicely"]);
  });

  it("IN-3 regression: editing a role updates that role, and never adds one", async () => {
    const { resume } = await seed();
    const puts = recordPutBodies();
    const user = renderAt(`/resumes/${resume.id}/check?step=journey`);
    await ready();

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
    const list = await screen.findByRole("list", { name: "Your resumes" });
    await user.click(within(list).getAllByRole("link", { name: /^Show details/ })[0]);
    await ready();
    await user.click(screen.getByRole("button", { name: /Your career journey/ }));

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
    await user.click(within(await screen.findByRole("list", { name: "Your resumes" })).getAllByRole("link", { name: /^Show details/ })[0]);
    await ready();
    await user.click(screen.getByRole("button", { name: /Your career journey/ }));
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

  it("IN-12, RSD-9: a role's finding chip opens that finding on step 2", async () => {
    const { resume } = await seed();
    const user = renderAt(`/resumes/${resume.id}/check?step=journey`);
    await ready();
    await user.click(screen.getByRole("button", { name: /^Show the \d+ findings? for Software Engineer · Invoicely$/ }));
    expect(screen.getByRole("button", { name: /Strova's findings/ })).toHaveAttribute("aria-current", "step");
    // The finding in view is about that role: the career strip outlines it (RSD-13).
    const strip = screen.getByRole("region", { name: "Career journey at a glance" });
    expect(strip.querySelector("[data-outlined]")).toHaveTextContent(/Invoicely|^$/);
    expect(strip.querySelectorAll("[data-outlined]")).not.toHaveLength(0);

    await user.click(screen.getByRole("button", { name: /Your career journey/ }));
    await user.click(screen.getByRole("button", { name: "Show the 1 finding for Skills" }));
    expect(within(finding()).getByRole("heading", { name: "A skill missing from Skills" })).toBeInTheDocument();
  });

  it("IN-12: What Strova checks opens from the step list footer", async () => {
    const { resume } = await seed();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    expect(screen.queryByText(/gaps over 3 months/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "What Strova checks ›" }));
    expect(screen.getByText(/gaps over 3 months/)).toBeInTheDocument();
  });

  it("IN-12: a missing date can be accepted with a reason, and stops counting as a finding", async () => {
    const { resume } = await seed();
    mockStore.db.resumes[0].resume!.roles[1].start = null;
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    const card = await openFinding(user, "No start date on Invoicely");
    expect(within(card).getByText(/Leaving old dates off on purpose is fine/)).toBeInTheDocument();
    const before = openCount();

    await user.click(within(card).getByRole("button", { name: "Accept: Left out on purpose (age bias)" }));
    expect(within(findingsView()).queryByRole("heading", { name: "No start date on Invoicely" })).not.toBeInTheDocument();
    const drawer = await acceptedDrawer(user);
    expect(within(drawer).getByText(/✓ Accepted: No start date on Invoicely/)).toHaveTextContent(
      "Left out on purpose (age bias)",
    );
    expect(openCount()).toBe(before - 1);
    const stored = () => (mockStore.db.resumes[0].accepted_issues ?? []).map((i) => i.key);
    await waitFor(() => expect(stored()).toEqual(["dates.missing-start:invoicely/software-engineer|why=on-purpose"]));

    // Changing the reason replaces the stored key; the finding stays accepted after a reload.
    await user.click(within(drawer).getByRole("button", { name: "Undo accepting No start date on Invoicely" }));
    await waitFor(() => expect(stored()).toEqual([]));
    await user.click(within(drawer).getByRole("button", { name: "Close" }));
    const again = await openFinding(user, "No start date on Invoicely");
    await user.click(within(again).getByRole("button", { name: "Accept: I don't remember" }));
    await waitFor(() => expect(stored()).toEqual(["dates.missing-start:invoicely/software-engineer|why=dont-remember"]));
  });

  it("IN-12: issues accepted earlier stay accepted when the page opens again", async () => {
    const { resume } = await seed();
    mockStore.db.resumes[0].accepted_issues = [
      { key: "consistency.skills-missing:celery", accepted_at: "2026-10-28T10:00:00Z" },
    ];
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    const drawer = await acceptedDrawer(user);
    expect(within(drawer).getByText("✓ Accepted: A skill missing from Skills")).toBeInTheDocument();
    expect(drawer).toHaveAccessibleName("Findings you accepted · 1");
  });

  it("IN-3: a new CV says where the user is, and ends in one next step, at the top and the bottom", async () => {
    const { resume, task } = await seed();
    const puts = recordPutBodies();
    // A new upload from the Resumes page brings its reading job.
    const user = renderAt(`/resumes/${resume.id}/check?task=${task?.id ?? ""}&step=journey`);
    await ready();
    expect(screen.getByRole("status")).toHaveTextContent("We read your resume. Check it, then continue.");
    const next = screen.getAllByRole("button", { name: "Add a job description to practice for" });
    expect(next).toHaveLength(2);
    expect(
      within(screen.getByRole("region", { name: "Next step" })).getByRole("button", { name: "Save and go back to resumes" }),
    ).toBeInTheDocument();
    await user.click(next[1]);
    expect(await screen.findByRole("heading", { level: 1, name: "Add a target role" })).toBeInTheDocument();
    expect(puts).toHaveLength(1);
  });

  it("IN-3: inside a rehearsal the next step is the interview plan, and a confirmed CV has no landing line", async () => {
    const { job, resume } = await seed();
    mockStore.db.resumes[0].confirmed_at = "2026-10-28T10:00:00Z";
    renderAt(`/jobs/${job.id}/resume/${resume.id}/check`);
    await ready();
    expect(screen.getAllByRole("button", { name: "Continue to your interview plan" })).toHaveLength(2);
    expect(screen.queryByText("We read your resume. Check it, then continue.")).not.toBeInTheDocument();
  });

  it("IN-3: keeps the v1 form when v2_enabled is off", async () => {
    setFeatureOverrides({ v2_enabled: false });
    const { resume } = await seed();
    renderAt(`/resumes/${resume.id}/check`);
    expect(await screen.findByRole("button", { name: "Confirm and continue" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Steps" })).not.toBeInTheDocument();
  });
});

describe("v2 coming back to a saved CV", () => {
  const ACCEPTED = { key: "consistency.skills-missing:celery", accepted_at: "2026-10-28T10:00:00Z" };
  const confirmed = () => {
    Object.assign(mockStore.db.resumes[0], { confirmed_at: "2026-10-28T10:00:00Z", accepted_issues: [ACCEPTED] });
  };
  const expectSameBreakdown = async () => {
    await ready();
    expect(screen.getByRole("button", { name: "Findings you accepted · 1 ›" })).toBeInTheDocument();
    expect(screen.queryByText("We read your resume. Check it, then continue.")).not.toBeInTheDocument();
    expect(screen.getByTestId("cvc-saved")).toHaveTextContent(/^Added [A-Z][a-z]{2} \d+(, \d{4})? · Last saved Oct 28(, 2026)?$/);
    expect(screen.getByRole("button", { name: "Use this resume for an interview" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to resumes" })).toBeInTheDocument();
  };

  it("IN-12, RMAP-2, RSD-1: the resume card shows the same open issues as the breakdown, and Show details opens it", async () => {
    await seed();
    confirmed();
    const user = renderAt("/resumes");
    const list = await screen.findByRole("list", { name: "Your resumes" });
    const row = within(list).getAllByRole("listitem")[0];
    expect(row).toHaveTextContent(/Added [A-Z][a-z]{2} \d+, \d{4} · Edited Oct 28/);
    const terms = within(row).getAllByRole("term").map((t) => t.textContent);
    expect(terms[1]).toMatch(/^open issues?$/);
    const open = Number(within(row).getAllByRole("definition")[1].textContent);
    const details = within(row).getByRole("link", { name: /^Show details/ });
    expect(details).toHaveAttribute("href", `/resumes/${mockStore.db.resumes[0].id}/check`);
    await user.click(details);
    await expectSameBreakdown();
    // D-4: the list and the check page count open issues the same way.
    expect(openCount()).toBe(open);
  });

  it("RMAP-2, RSD-3: one list; Rename and Delete sit in the card footer, with no More menu", async () => {
    await seed();
    const user = renderAt("/resumes");
    const list = await screen.findByRole("list", { name: "Your resumes" });
    expect(screen.queryByRole("list", { name: "Saved resumes" })).not.toBeInTheDocument();
    expect(screen.queryByText("Rename or delete resumes")).not.toBeInTheDocument();
    const row = within(list).getAllByRole("listitem")[0];
    // RMAP-3: a resume never saved from the editor has no "Not checked yet" next to its issues.
    expect(row).not.toHaveTextContent(/checked/i);
    expect(row).not.toHaveTextContent(/Edited/);
    expect(within(row).getByRole("link", { name: /^Show details/ })).toBeInTheDocument();
    expect(within(row).queryByText(/More/)).not.toBeInTheDocument();

    await user.click(within(row).getByRole("button", { name: /^Rename / }));
    const field = within(row).getByRole("textbox", { name: "New name" });
    await user.clear(field);
    await user.click(within(row).getByRole("button", { name: "Save name" }));
    expect(within(row).getByRole("alert")).toHaveTextContent("Enter a name.");
    await user.type(field, "Payments resume");
    await user.click(within(row).getByRole("button", { name: "Save name" }));
    expect(await within(list).findByRole("heading", { name: "Payments resume" })).toBeInTheDocument();
    expect(mockStore.db.resumes[0].name).toBe("Payments resume");
  });

  it("RMAP-2: Delete asks first, then removes the resume from the list", async () => {
    await seed();
    const user = renderAt("/resumes");
    const list = await screen.findByRole("list", { name: "Your resumes" });
    const row = within(list).getAllByRole("listitem")[0];
    await user.click(within(row).getByRole("button", { name: /^Delete / }));
    const dialog = within(row).getByRole("dialog", { name: "Delete this resume?" });
    expect(dialog).toHaveTextContent("Your newest other resume becomes your default resume.");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("No resume yet. Add one and Strova reads it.")).toBeInTheDocument();
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
    await ready();
    expect(screen.queryByText("We read your resume. Check it, then continue.")).not.toBeInTheDocument();
    expect(screen.getByTestId("cvc-saved")).toHaveTextContent(/Not saved yet$/);
    await user.click(screen.getAllByRole("button", { name: "Use this resume for an interview" })[0]);
    expect(await screen.findByRole("heading", { level: 1, name: "Add a target role" })).toBeInTheDocument();
    expect(puts).toHaveLength(1);
  });

});
