/**
 * RSD-7, RSD-8, RSD-9, RSD-10, RSD-13: the guided check page (mockup "Check C2: Guided, revised
 * (v2)"): the header, the step list, the journey timeline, one finding at a time and the career
 * strip. Runs with v2 on against the MSW mocks.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "../../../api/inputs";
import { AppRoutes, createQueryClient } from "../../../App";
import { mockStore } from "../../../mocks/node";
import { setFeatureOverrides } from "../../../theme/features";
import { journeyLine } from "../ResumeCheckV2";
import type { ResumeIssue } from "../resumeChecks";
import { careerSegments, stripSummary } from "./CareerStrip";
import type { CvRole } from "./draft";
import { dateFields, orderFindings } from "./FindingsStep";
import { gapLabel, gapMonths } from "./JourneyStep";
import { defaultStep, parseStep } from "./StepList";

const EMAIL = "ana@example.com";

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  mockStore.db.users[EMAIL] = {
    id: "00000000-0000-4000-8000-0000000000a1",
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email: EMAIL,
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
    tracing_consent: false,
    tracing_consent_available: false,
  };
  mockStore.db.auth = { status: "signed_in", email: EMAIL, userEmail: EMAIL };
});
afterEach(() => setFeatureOverrides({}));

async function seed() {
  const { job_target: job } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  await jobTargetsApi.get(job.id);
  const form = new FormData();
  form.append("text", "Backend engineer, seven years of Python.");
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  return { job, resume, record: mockStore.db.resumes.find((r) => r.id === resume.id)! };
}

function Where() {
  const { search } = useLocation();
  return <span data-testid="search">{search}</span>;
}

function renderAt(path: string) {
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

const ready = () => screen.findByRole("navigation", { name: "Steps" });
const stepButton = (name: RegExp) => within(screen.getByRole("navigation", { name: "Steps" })).getByRole("button", { name });
const current = () => screen.getByRole("navigation", { name: "Steps" }).querySelector('[aria-current="step"]');
const finding = () => within(screen.getByTestId("findings-step")).getByRole("article");

describe("RSD-7: the header", () => {
  it("RSD-7: the name, then Set as default; the dates and Used by N roles; Upload a new version and the primary action", async () => {
    const { resume, job } = await seed();
    // A second resume so this one is not the default.
    const form = new FormData();
    form.append("text", "Platform engineer, Kubernetes.");
    const second = await resumesApi.upload(form);
    await resumesApi.get(second.resume.id);
    await fetch(`${location.origin}/api/roles/${job.id}/interviews`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ interview_types: ["behavioral"], resume_id: second.resume.id }),
    });
    const user = renderAt(`/resumes/${second.resume.id}/check`);
    await ready();
    const name = mockStore.db.resumes.find((r) => r.id === second.resume.id)?.name ?? "";
    expect(screen.getByRole("heading", { level: 1, name })).toBeInTheDocument();
    expect(screen.getByTestId("cvc-saved")).toHaveTextContent(/^Added [A-Z][a-z]{2} \d+(, \d{4})? · Not saved yet$/);
    expect(await screen.findByTestId("used-by")).toHaveTextContent("Used by 1 role");
    expect(screen.getByRole("link", { name: "Upload a new version" })).toHaveAttribute("href", "/start");
    expect(screen.getByRole("button", { name: "Use this resume for an interview" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Set as default" }));
    expect(await screen.findByText("Default")).toBeInTheDocument();
    await waitFor(() => expect(mockStore.db.resumes.find((r) => r.id === second.resume.id)?.is_main).toBe(true));
    expect(mockStore.db.resumes.find((r) => r.id === resume.id)?.is_main).toBe(false);
  });

  it("RSD-7: the default resume shows the Default chip, and the roles link is hidden at 0", async () => {
    const { resume } = await seed();
    renderAt(`/resumes/${resume.id}/check`);
    await ready();
    expect(screen.getByText("Default")).toHaveClass("sx-chip");
    expect(screen.queryByRole("button", { name: "Set as default" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("used-by")).not.toBeInTheDocument();
  });

  it("RSD-7, D-9: onboarding keeps the Steps header and Continue to your interview plan", async () => {
    const { resume, job } = await seed();
    renderAt(`/jobs/${job.id}/resume/${resume.id}/check`);
    await ready();
    expect(screen.getByRole("heading", { level: 1, name: "Check your resume" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Continue to your interview plan" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Upload a new version" })).not.toBeInTheDocument();
  });
});

describe("RSD-8: the step list", () => {
  it("RSD-8: four steps with names, counts and one line; findings first when one is open; the step is in the URL", async () => {
    const { resume } = await seed();
    const user = renderAt(`/resumes/${resume.id}/check?task=t1`);
    await ready();
    const nav = screen.getByRole("navigation", { name: "Steps" });
    const names = within(nav)
      .getAllByRole("button")
      .map((b) => b.querySelector(".cvc-step__name")?.textContent);
    expect(names).toEqual(["Your career journey", "Strova's findings", "Stories to tell in interviews", "Stronger resume lines"]);
    expect(stepButton(/Your career journey/)).toHaveTextContent(/\d+ roles? · \d+ years? · \d+ achievements?/);
    expect(stepButton(/Strova's findings/)).toHaveTextContent(/and the fixes she recommends · \d+ high/);
    expect(stepButton(/Stories to tell/)).toHaveTextContent("Resume → Interview");
    expect(stepButton(/Stronger resume lines/)).toHaveTextContent("Your stories → Resume");
    // No readiness bar (D-5).
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();

    expect(current()).toBe(stepButton(/Strova's findings/));
    await user.click(stepButton(/Your career journey/));
    expect(current()).toBe(stepButton(/Your career journey/));
    // Other params stay.
    expect(screen.getByTestId("search")).toHaveTextContent("?task=t1&step=journey");
    await waitFor(() => expect(stepButton(/Stories to tell/).querySelector(".cvc-step__num")).toHaveTextContent(/^\d+$/));
  });

  it("RSD-8: ?step= opens that step; without findings the page opens on the journey", async () => {
    const { resume } = await seed();
    renderAt(`/resumes/${resume.id}/check?step=lines`);
    await ready();
    expect(current()).toBe(stepButton(/Stronger resume lines/));
    expect(parseStep("lines", false)).toBe("lines");
    expect(parseStep("nope", false)).toBeNull();
    expect(defaultStep(0, false)).toBe("journey");
    expect(defaultStep(3, false)).toBe("findings");
  });

  it("RSD-8, D-9: onboarding shows steps 1 and 2 only and opens on the journey", async () => {
    const { resume, job } = await seed();
    renderAt(`/jobs/${job.id}/resume/${resume.id}/check?step=stories`);
    await ready();
    const nav = screen.getByRole("navigation", { name: "Steps" });
    expect(within(nav).getAllByRole("button")).toHaveLength(2);
    expect(current()).toBe(stepButton(/Your career journey/));
    expect(parseStep("stories", true)).toBeNull();
    expect(defaultStep(5, true)).toBe("journey");
  });
});

describe("RSD-9: the journey", () => {
  it("RSD-9: the roles on a timeline, newest first, with a dashed gap and a link that opens that finding", async () => {
    const { resume, record } = await seed();
    record.resume!.roles[1].end = "2020-06"; // Invoicely ends 9 months before Shoply starts
    const user = renderAt(`/resumes/${resume.id}/check?step=journey`);
    await ready();
    const timeline = screen.getByRole("list", { name: "Roles, newest first" });
    const items = [...timeline.querySelectorAll<HTMLElement>(":scope > li")];
    expect(items[0]).toHaveTextContent("Shoply");
    expect(items[1]).toHaveTextContent("Invoicely");
    expect(items[0]).toHaveAttribute("data-gap", "true");
    expect(items[0].querySelector(".cvc-tl__line--gap")).not.toBeNull();
    const link = within(items[0]).getByRole("button", { name: /^9-month gap · .* · see the fix$/ });
    await user.click(link);
    expect(current()).toBe(stepButton(/Strova's findings/));
    expect(within(finding()).getByRole("heading", { name: /gap/i })).toBeInTheDocument();
  });

  it("RSD-9: summary first, then the roles, then skills, education and certifications as three tiles", async () => {
    const { resume } = await seed();
    renderAt(`/resumes/${resume.id}/check?step=journey`);
    await ready();
    const view = screen.getByRole("region", { name: "Your career journey" });
    const order = [
      within(view).getByRole("region", { name: "Summary and intro" }),
      within(view).getByRole("list", { name: "Roles, newest first" }),
      within(view).getByRole("region", { name: /^Skills/ }),
      within(view).getByRole("region", { name: "Education" }),
      within(view).getByRole("region", { name: "Certifications" }),
    ];
    for (let i = 1; i < order.length; i += 1) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(screen.getByRole("region", { name: "Education" }).parentElement).toHaveClass("cvc-pair");
    expect(screen.getByRole("button", { name: /^Show the \d+ findings? for Software Engineer · Invoicely$/ })).toHaveTextContent(
      /^\d+ findings?$/,
    );
  });
});

describe("RSD-10: Strova's findings", () => {
  it("RSD-10: one finding at a time, high first, with previous and next and the position", async () => {
    const { resume, record } = await seed();
    record.resume!.roles[1].end = "2020-06";
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    const position = () => within(finding()).getByTestId("finding-position").textContent ?? "";
    // The gap is the only date finding here, so it leads (medium); high ones would come first.
    expect(position()).toMatch(/^Finding 1 of (\d+) · (high|medium)$/);
    const total = Number(/of (\d+)/.exec(position())![1]);
    expect(within(finding()).getByRole("button", { name: "Previous finding" })).toBeDisabled();
    await user.click(within(finding()).getByRole("button", { name: "Next finding" }));
    expect(position()).toMatch(new RegExp(`^Finding 2 of ${total} · `));
    await user.click(within(finding()).getByRole("button", { name: "Previous finding" }));
    expect(position()).toMatch(/^Finding 1 of/);
    const rows = within(screen.getByRole("list", { name: "Next findings" })).getAllByRole("button");
    expect(rows).toHaveLength(total - 1);
    await user.click(rows[rows.length - 1]);
    expect(position()).toMatch(new RegExp(`^Finding ${total} of ${total}`));
    expect(within(finding()).getByRole("button", { name: "Next finding" })).toBeDisabled();
  });

  it("RSD-10: a gap shows both dates in Strova recommends, every accept reason, and the practice link", async () => {
    const { resume, record } = await seed();
    record.resume!.roles[1].end = "2020-06";
    renderAt(`/resumes/${resume.id}/check`);
    await ready();
    const card = finding();
    expect(within(card).getByRole("heading", { name: /gap/i })).toBeInTheDocument();
    expect(within(card).getByText("Strova recommends")).toBeInTheDocument();
    expect(within(card).getByLabelText("Invoicely ended")).toHaveValue("2020-06");
    expect(within(card).getByLabelText("Shoply started")).toHaveValue("2021-03");
    expect(within(card).getByRole("button", { name: "Save dates" })).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /Practice "tell me about this gap"/ }).getAttribute("href")).toMatch(/^\/coach\/new\?ask=/);
  });

  it("RSD-10: a skills finding offers Add {skills}, which saves and moves on", async () => {
    const { resume } = await seed();
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    await user.click(within(screen.getByRole("list", { name: "Next findings" })).getByRole("button", { name: /A skill missing from Skills/ }));
    await user.click(within(finding()).getByRole("button", { name: "Add Celery" }));
    await waitFor(() => expect(mockStore.db.resumes[0].resume?.skills).toContain("Celery"));
    expect(screen.queryByRole("heading", { name: "A skill missing from Skills" })).not.toBeInTheDocument();
  });

  it("RSD-10: a finding with no form keeps a normal button (not full width) that opens its field on step 1", async () => {
    const { resume, record } = await seed();
    // A copy: the mock's fixture resume is shared with the other tests.
    record.resume = structuredClone(record.resume!);
    record.resume.roles.push({ company: "Shoply", title: "Software Engineer I", start: "2019-01", end: "2021-02", achievements: ["Fixed checkout bugs"], skills: [] });
    record.resume.roles[1].start = "2016-01";
    record.resume.roles[1].end = "2018-12";
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    await user.click(within(screen.getByRole("list", { name: "Next findings" })).getByRole("button", { name: /Shoply listed 2 times/ }));
    const open = within(finding()).getByRole("button", { name: "Open the role" });
    // The Strova recommends box is a column; the button sits in a row so it keeps its pill shape.
    expect(open.parentElement).toHaveClass("row");
    expect(open.parentElement?.parentElement).toHaveClass("cvc-recommends");
    await user.click(open);
    expect(current()).toBe(stepButton(/Your career journey/));
    expect(screen.getByRole("group", { name: /^Editing · Software Engineer/ })).toBeInTheDocument();
  });

  it("RSD-10: with nothing open it says so and links to step 1", async () => {
    const { resume, record } = await seed();
    const { checkResume, thisMonth } = await import("../resumeChecks");
    const all = checkResume(record.resume!, { today: thisMonth(), job: null });
    record.accepted_issues = all.map((i) => ({ key: i.key, accepted_at: "2026-10-28T10:00:00Z" }));
    const user = renderAt(`/resumes/${resume.id}/check?step=findings`);
    await ready();
    expect(screen.getByText("Nothing to fix. Your resume reads well.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "See your career journey" }));
    expect(current()).toBe(stepButton(/Your career journey/));
  });

  it("RSD-10: findings are ordered high first, then in the order found", () => {
    const f = (key: string, severity: ResumeIssue["severity"]) => ({ key, severity }) as ResumeIssue;
    expect(orderFindings([f("a", "low"), f("b", "high"), f("c", "medium"), f("d", "high")]).map((i) => i.key)).toEqual([
      "b",
      "d",
      "a",
      "c",
    ]);
    const gap = { group: "dates", target: { section: "role", role: 0, field: "start" }, roles: [1, 0], gap: { from: "a", to: "b" } } as ResumeIssue;
    expect(dateFields(gap)).toEqual([
      { role: 1, field: "end" },
      { role: 0, field: "start" },
    ]);
  });
});

describe("RSD-13: the career strip", () => {
  it("RSD-13: shows under steps 2 to 4, not on step 1; Open and edit goes to step 1", async () => {
    const { resume, record } = await seed();
    record.resume!.roles[1].end = "2020-06";
    const user = renderAt(`/resumes/${resume.id}/check`);
    await ready();
    const strip = screen.getByRole("region", { name: "Career journey at a glance" });
    const img = within(strip).getByRole("img");
    expect(img).toHaveAccessibleName(/^Timeline: Invoicely 2018 to 2020, gap, Shoply 2021 to now$/);
    expect(strip.querySelector(".cvc-strip__seg--gap")).not.toBeNull();
    // The roles of the current finding (the gap) are outlined.
    expect(strip.querySelectorAll("[data-outlined]")).toHaveLength(2);
    await user.click(within(strip).getByRole("button", { name: "Open and edit" }));
    expect(current()).toBe(stepButton(/Your career journey/));
    expect(screen.queryByRole("region", { name: "Career journey at a glance" })).not.toBeInTheDocument();
  });

  it("RSD-13: segments are sized by months, oldest first, with gaps over 3 months", () => {
    const role = (company: string, start: string, end: string): CvRole => ({
      key: 1,
      company,
      title: "Engineer",
      start,
      end,
      achievements: [],
      skills: [],
    });
    const roles = [role("Ledgerline", "2021-03", ""), role("Kitepath", "2015-08", "2017-07"), role("Studio Nine", "2014", "2015-03")];
    const built = careerSegments(roles, "2026-11")!;
    expect(built.segments.map((s) => `${s.kind}:${s.label}:${s.to - s.from}`)).toEqual([
      "role:Studio Nine:14",
      "gap:gap:5",
      "role:Kitepath:23",
      "gap:gap:44",
      "role:Ledgerline:68",
    ]);
    expect(stripSummary(built.segments, 2026 * 12 + 10)).toBe(
      "Timeline: Studio Nine 2014 to 2015, gap, Kitepath 2015 to 2017, gap, Ledgerline 2021 to now",
    );
    expect(gapMonths(roles[1], roles[2])).toBe(5);
    expect(
      gapLabel(
        { target: { section: "role", role: 1, field: "start" }, roles: [2, 1], gap: { from: "Mar 2015", to: "Aug 2015" }, detail: "" } as unknown as ResumeIssue,
        roles,
      ),
    ).toBe("5-month gap · Mar 2015 to Aug 2015 · see the fix");
    expect(journeyLine(roles, "2026-11")).toBe("3 roles · 13 years · 0 achievements");
  });
});
