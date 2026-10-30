/**
 * Tester feedback of 2026-10-28: accepted missing dates (IN-12), skill chips that fit their card
 * (IN-12), the step bar of the add flow (IN-4) and links kept in pasted recruiter notes (IN-4).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "../../api/inputs";
import type { ResumeOut } from "../../api/types";
import { AppRoutes, createQueryClient } from "../../App";
import { resume as fixtureResume } from "../../mocks/fixtures";
import { mockStore } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";
import { acceptedKeySet, parseStoredKey, storedKey } from "./acceptedIssues";
import { htmlToTextWithLinks } from "./pasteLinks";
import { KEY_MAX } from "./resumeChecks";
import { resumeIssueCounts } from "./resumeSummary";
import { STEP_NOTES } from "./steps";

const styles = readFileSync(join(resolve(__dirname), "../../styles.css"), "utf8");

beforeEach(() => setFeatureOverrides({ v2_enabled: true }));
afterEach(() => setFeatureOverrides({}));

describe("accepted issues with a reason", () => {
  it("IN-12: stores the reason in the key and reads it back", () => {
    expect(storedKey("dates.missing-start:acme/pm", "on-purpose")).toBe("dates.missing-start:acme/pm|why=on-purpose");
    expect(storedKey("dates.missing-start:acme/pm")).toBe("dates.missing-start:acme/pm");
    expect(parseStoredKey("dates.missing-start:acme/pm|why=dont-remember")).toEqual({
      key: "dates.missing-start:acme/pm",
      reason: "dont-remember",
    });
    expect(parseStoredKey("consistency.skills-missing:celery")).toEqual({ key: "consistency.skills-missing:celery", reason: null });
    // Too long for the API with the reason: accepted without it.
    const long = "x".repeat(KEY_MAX - 2);
    expect(storedKey(long, "on-purpose")).toBe(long);
  });

  it("IN-12: an accepted missing date stops counting as an issue on Resumes and Home", () => {
    const cv = { ...fixtureResume, roles: [fixtureResume.roles[0], { ...fixtureResume.roles[1], start: null }] };
    const record = { resume: cv, accepted_issues: [] } as unknown as ResumeOut;
    const before = resumeIssueCounts(record, "2026-10")!;
    const accepted = {
      ...record,
      accepted_issues: [{ key: "dates.missing-start:invoicely/software-engineer|why=on-purpose", accepted_at: "2026-10-28T10:00:00Z" }],
    } as ResumeOut;
    const after = resumeIssueCounts(accepted, "2026-10")!;
    expect(after.open).toBe(before.open - 1);
    expect(after.accepted).toBe(1);
    expect(acceptedKeySet(accepted.accepted_issues)).toEqual(new Set(["dates.missing-start:invoicely/software-engineer"]));
  });
});

describe("skill chips", () => {
  it("IN-12: chips in a list wrap inside their card instead of overflowing", () => {
    const rule = /\.cvc-chips \.cvc-chip \{([^}]*)\}/.exec(styles)?.[1] ?? "";
    expect(rule).toMatch(/white-space:\s*normal/);
    expect(rule).toMatch(/overflow-wrap:\s*anywhere/);
    expect(rule).toMatch(/max-width:\s*100%/);
  });
});

describe("pasted recruiter notes", () => {
  it("IN-4: keeps link addresses as markdown, or as the bare URL when the text is the URL", () => {
    const html =
      '<p>Hi Ana, the loop is on <b>Tuesday</b>. Read <a href="https://example.com/guide">our interview guide</a>.</p>' +
      '<ul><li>Team page: <a href="https://example.com/team">https://example.com/team</a></li>' +
      '<li>Mail <a href="mailto:sam@example.com">sam@example.com</a></li></ul>' +
      '<p><a href="javascript:alert(1)">bad</a></p>';
    expect(htmlToTextWithLinks(html)).toBe(
      "Hi Ana, the loop is on Tuesday. Read [our interview guide](https://example.com/guide).\n" +
        "- Team page: https://example.com/team\n" +
        "- Mail sam@example.com\n" +
        "bad",
    );
    expect(htmlToTextWithLinks("<p>No links here</p>")).toBeNull();
  });
});

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

describe("the add flow's step bar", () => {
  it("IN-4: Add context says how the user got there, links back to done steps and offers Skip at the top", async () => {
    const { job, resume } = await seed();
    const user = renderAt(`/jobs/${job.id}/context?resume=${resume.id}`);
    expect(await screen.findByRole("heading", { name: "Add context (optional)" })).toBeInTheDocument();
    expect(screen.getByTestId("steps-note")).toHaveTextContent(STEP_NOTES.context);
    const steps = screen.getByRole("list", { name: "Setup steps" });
    expect(within(steps).getByRole("link", { name: /^Job description \(done\)/ })).toHaveAttribute("href", `/jobs/${job.id}/confirm`);
    const cv = within(steps).getByRole("link", { name: /^Your resume \(done\)/ });
    expect(cv).toHaveAttribute("href", `/jobs/${job.id}/resume/${resume.id}/check`);
    // The current step is not a link.
    expect(within(steps).getByText("Your plan").closest("li")).toHaveAttribute("aria-current", "step");
    expect(within(steps).queryByRole("link", { name: /Your plan/ })).not.toBeInTheDocument();

    // Skip sits under the title, before the form.
    const skip = screen.getByRole("button", { name: "Skip and open my plan" });
    expect(skip.compareDocumentPosition(screen.getByLabelText("Interview stage")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await user.click(cv);
    expect(await screen.findByRole("heading", { name: "Check your resume" })).toBeInTheDocument();
    expect(screen.getByTestId("steps-note")).toHaveTextContent(STEP_NOTES.check);
  });

  it("IN-4: pasting rich text into the recruiter notes keeps the links", async () => {
    const { job, resume } = await seed();
    renderAt(`/jobs/${job.id}/context?resume=${resume.id}`);
    const notes = await screen.findByLabelText("Notes from the recruiter");
    const html = 'Prep with <a href="https://example.com/prep">this doc</a>.';
    fireEvent.paste(notes, {
      clipboardData: { getData: (type: string) => (type === "text/html" ? html : "Prep with this doc.") },
    });
    expect(notes).toHaveValue("Prep with [this doc](https://example.com/prep).");
  });
});
