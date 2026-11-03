/**
 * RSD-1, RSD-2, RSD-3, RSD-16: the Resumes list on the shared card shell (mockup "Resumes list (2
 * columns)"), with v2 on, against the MSW mocks.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "../../api/inputs";
import type { ResumeOut } from "../../api/types";
import { AppRoutes, createQueryClient } from "../../App";
import { EMPTY_PROFILE } from "../../mocks/handlers";
import { mockStore, server } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";
import { MAX_RESUMES } from "../../limits";
import { checkResume, thisMonth } from "../onboarding/resumeChecks";
import { resumeIssueCounts } from "../onboarding/resumeSummary";
import { HIGH_MARK_LABEL, resumeStats, usingRoleCount } from "./ResumesListPage";

const USER_ID = "00000000-0000-4000-8000-0000000000a1";
const EMAIL = "ana@example.com";
const RESUME_TEXT = "Backend engineer, Python and Go. Led the move of 30 services to PostgreSQL.";

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
  mockStore.db.profiles[EMAIL] = { ...EMPTY_PROFILE, plan_style: "weekly" };
  setFeatureOverrides({ v2_enabled: true });
});
afterEach(() => setFeatureOverrides({}));

function renderApp(path = "/resumes") {
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

async function addResume(name?: string): Promise<ResumeOut> {
  const form = new FormData();
  form.append("text", RESUME_TEXT);
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  if (name) await resumesApi.rename(resume.id, name);
  return mockStore.db.resumes.find((r) => r.id === resume.id) as ResumeOut;
}

/** A role on this resume, through the interviews endpoint, as the app creates it. */
async function roleOn(resumeId: string) {
  const { job_target: created } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  const job = await jobTargetsApi.get(created.id);
  await fetch(`${location.origin}/api/roles/${job.id}/interviews`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ interview_types: ["behavioral"], resume_id: resumeId }),
  });
}

/** A high-severity issue: the first role ends before it starts. */
function withHighIssue(record: ResumeOut) {
  const role = record.resume?.roles[0];
  if (role) {
    role.start = "2024-06";
    role.end = "2023-01";
  }
}

/** No high-severity issue: accept the high ones, as a user can (IN-12). */
function withoutHighIssue(record: ResumeOut) {
  if (!record.resume) return;
  const high = checkResume(record.resume, { today: thisMonth(), job: null }).filter((i) => i.severity === "high");
  record.accepted_issues = high.map((i) => ({ key: i.key, accepted_at: "2026-10-28T10:00:00Z" }));
}

const cardOf = async (name: string) => {
  const list = await screen.findByRole("list", { name: "Your resumes" });
  const heading = await within(list).findByRole("heading", { level: 2, name });
  return heading.closest("section") as HTMLElement;
};
const tiles = (card: HTMLElement) =>
  within(card)
    .queryAllByRole("term")
    .map((t, i) => `${within(card).getAllByRole("definition")[i].textContent} ${t.textContent}`);

describe("RSD-1: the cards", () => {
  it("RSD-1: one card per resume in a two-column grid, with three tiles and the dates, and no company names", async () => {
    const main = await addResume("Senior SWE resume");
    await addResume("Platform lead resume");
    await roleOn(main.id);
    renderApp();
    const list = await screen.findByRole("list", { name: "Your resumes" });
    expect(list.closest(".sx-grid2")).toHaveClass("stretch");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    for (const item of items) expect(within(item).getByRole("region")).toHaveClass("sx-summary");

    const card = await cardOf("Senior SWE resume");
    expect(within(card).getByText("Default")).toBeInTheDocument();
    await waitFor(() => expect(tiles(card)[0]).toBe("1 role"));
    await waitFor(() => expect(tiles(card)[2]).toMatch(/^\d+ story ideas?$/));
    expect(tiles(card)[1]).toMatch(/^\d+ open issues?$/);
    expect(card).toHaveTextContent(/Added [A-Z][a-z]{2} \d+, \d{4}/);
    // The page no longer names the companies that use a resume.
    expect(card).not.toHaveTextContent(/Used by/);
    // The tiles are not interactive.
    expect(card.querySelector(".sx-summary__stats")?.querySelectorAll("a, button")).toHaveLength(0);
  });

  it("RSD-1: the roles count is the rule behind usedBy; story ideas use the story-ideas query", async () => {
    const r = await addResume("Senior SWE resume");
    renderApp();
    const card = await cardOf("Senior SWE resume");
    const ideas = (await (await fetch(`${location.origin}/api/resumes/${r.id}/story-ideas`)).json()) as { ideas: unknown[] };
    await waitFor(() => expect(tiles(card)[2]).toBe(`${ideas.ideas.length} ${ideas.ideas.length === 1 ? "story idea" : "story ideas"}`));
    expect(tiles(card)[0]).toBe("0 roles");
    expect(usingRoleCount(undefined, r.id)).toBeNull();
  });
});

describe("RSD-2: the open issues tile", () => {
  it("RSD-2: is amber with a spoken ▲ when an issue is high, and plain otherwise", async () => {
    const high = await addResume("Senior SWE resume");
    withHighIssue(high);
    withoutHighIssue(await addResume("Platform lead resume"));
    renderApp();

    const amber = await cardOf("Senior SWE resume");
    const counts = resumeIssueCounts(high);
    expect(counts?.high).toBeGreaterThan(0);
    const mark = await within(amber).findByRole("img", { name: HIGH_MARK_LABEL });
    expect(mark.closest(".sx-stat")).toHaveClass("sx-stat--warn");
    expect(tiles(amber)[1]).toBe(`${counts?.open} ${counts?.open === 1 ? "open issue" : "open issues"}`);

    const plain = await cardOf("Platform lead resume");
    const other = resumeIssueCounts(mockStore.db.resumes.find((r) => r.name === "Platform lead resume") as ResumeOut);
    expect(other?.high).toBe(0);
    expect(within(plain).queryByRole("img", { name: HIGH_MARK_LABEL })).not.toBeInTheDocument();
    expect(plain.querySelector(".sx-stat--warn")).toBeNull();
  });

  it("RSD-2: singular labels for 1, '—' while a count loads, and no sub-text", () => {
    expect(resumeStats(1, { open: 1, high: 1 }, 1)).toEqual([
      { value: 1, label: "role" },
      { value: 1, label: "open issue", tone: "warn", markLabel: HIGH_MARK_LABEL },
      { value: 1, label: "story idea" },
    ]);
    expect(resumeStats(7, { open: 4, high: 0 }, 18)).toEqual([
      { value: 7, label: "roles" },
      { value: 4, label: "open issues" },
      { value: 18, label: "story ideas" },
    ]);
    expect(resumeStats(null, null, null).map((t) => t.value)).toEqual(["—", "—", "—"]);
  });
});

describe("RSD-3: the footer", () => {
  it("RSD-3: Show details, then Set as default (not on the default), Rename and Delete; no Open link and no More menu", async () => {
    const main = await addResume("Senior SWE resume");
    const other = await addResume("Platform lead resume");
    const user = renderApp();

    const def = await cardOf("Senior SWE resume");
    const foot = def.querySelector(".sx-summary__foot") as HTMLElement;
    expect([...foot.querySelectorAll("a, button")].map((el) => el.getAttribute("aria-label"))).toEqual([
      "Show details: Senior SWE resume",
      "Rename Senior SWE resume",
      "Delete Senior SWE resume",
    ]);
    expect(within(def).getByRole("link", { name: /^Show details/ })).toHaveAttribute("href", `/resumes/${main.id}/check`);
    expect(within(def).queryByText(/More/)).not.toBeInTheDocument();
    expect(within(def).queryByRole("link", { name: /^Open/ })).not.toBeInTheDocument();
    // The card is not a link (D-2).
    expect(def.closest("a")).toBeNull();

    const card = await cardOf("Platform lead resume");
    await user.click(within(card).getByRole("button", { name: "Set Platform lead resume as default" }));
    await waitFor(() => expect(mockStore.db.resumes.find((r) => r.id === other.id)?.is_main).toBe(true));
    await waitFor(async () => expect(within(await cardOf("Platform lead resume")).getByText("Default")).toBeInTheDocument());
  });

  it("RSD-3: Rename replaces the card body with the form; Delete opens the dialog with the RMAP-5 roles note", async () => {
    const main = await addResume("Senior SWE resume");
    await roleOn(main.id);
    const user = renderApp();
    const card = await cardOf("Senior SWE resume");

    await user.click(within(card).getByRole("button", { name: "Rename Senior SWE resume" }));
    const form = within(card).getByRole("form", { name: "Rename Senior SWE resume" });
    expect(within(form).getByRole("textbox", { name: "New name" })).toHaveValue("Senior SWE resume");
    expect(within(card).queryByRole("link", { name: /^Show details/ })).not.toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Cancel" }));

    const del = within(card).getByRole("button", { name: "Delete Senior SWE resume" });
    await waitFor(() => expect(tiles(card)[0]).toBe("1 role"));
    await user.click(del);
    const dialog = within(card.closest("li") as HTMLElement).getByRole("dialog", { name: "Delete this resume?" });
    expect(within(dialog).getByTestId("delete-roles-note")).toHaveTextContent(/uses this resume\./);
    await user.click(within(dialog).getByRole("button", { name: "Keep it" }));
    expect(del).toHaveFocus();
  });

  it("RSD-3: a resume still being read shows empty tiles, 'Being read' and only Rename and Delete", async () => {
    await addResume("Senior SWE resume");
    const reading = await addResume("Data engineering resume");
    Object.assign(reading, { status: "pending", resume: null, confirmed_at: null });
    // No task for it, so the mock keeps it pending.
    renderApp();
    const card = await cardOf("Data engineering resume");
    expect(within(card).getByText("Being read")).toBeInTheDocument();
    expect(card).toHaveTextContent("Strova is reading this resume. The numbers show when she is done.");
    expect(within(card).queryAllByRole("term")).toHaveLength(0);
    expect(card.querySelectorAll(".sx-stat--empty")).toHaveLength(3);
    const controls = [...(card.querySelector(".sx-summary__foot") as HTMLElement).querySelectorAll("a, button")];
    expect(controls.map((el) => el.textContent)).toEqual(["Rename", "Delete"]);
  });

  it("RSD-3: an Add a resume card ends the grid while under the limit, and is gone at the limit", async () => {
    await addResume("Senior SWE resume");
    await addResume("Platform lead resume");
    renderApp();
    const add = await screen.findByRole("link", { name: /Add a resume.*slots left/ });
    expect(add).toHaveAttribute("href", "/start");
    expect(add).toHaveTextContent(`${MAX_RESUMES - 2} slots left. Add the version you sent for a role.`);
    expect(add.closest("ul")).toBeNull();
  });

  it("RSD-3: with five resumes there is no Add card, and the full notice shows", async () => {
    for (let i = 0; i < MAX_RESUMES; i += 1) await addResume(`Resume ${i + 1}`);
    renderApp();
    expect(await screen.findByTestId("resumes-full")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /slots? left/ })).not.toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Your resumes" })).getAllByRole("listitem")).toHaveLength(MAX_RESUMES);
  });
});

describe("RSD-16: story ideas on the list", () => {
  it("RSD-16: one counts request for every card, no per-card story-ideas request, and the same numbers", async () => {
    const senior = await addResume("Senior SWE resume");
    await addResume("Platform lead resume");
    const reading = await addResume("Data engineering resume");
    Object.assign(reading, { status: "pending", resume: null, confirmed_at: null });
    // One idea set aside on the first resume, so the counts differ.
    const first = (await (await fetch(`${location.origin}/api/resumes/${senior.id}/story-ideas`)).json()) as {
      ideas: { resume_line_ref: string }[];
    };
    await resumesApi.dismissIdea(senior.id, first.ideas[0].resume_line_ref);
    const perCard: string[] = [];
    const counts: string[] = [];
    const onStart = ({ request }: { request: Request }) => {
      if (request.method !== "GET") return;
      const path = new URL(request.url).pathname;
      if (/\/resumes\/[^/]+\/story-ideas$/.test(path)) perCard.push(path);
      if (path.endsWith("/story-ideas/counts")) counts.push(path);
    };
    server.events.on("request:start", onStart);
    try {
      renderApp();
      const card = await cardOf("Senior SWE resume");
      await waitFor(() => expect(tiles(card)[2]).toMatch(/^\d+ story ideas?$/));
      expect(tiles(card)[2]).toMatch(new RegExp(`^${first.ideas.length - 1} `));
      const reader = await cardOf("Data engineering resume");
      expect(within(reader).queryAllByRole("term")).toHaveLength(0);
      expect(counts).toHaveLength(1);
      expect(perCard).toEqual([]);
    } finally {
      server.events.removeListener("request:start", onStart);
    }
  });
});
