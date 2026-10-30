/**
 * U11: Home with Strova (HO-1) and the plan in both styles (PS-3, PS-4), against the MSW mocks
 * (mocks/personalPlanHandlers.ts builds the plan from the other mocks). Also the coverage moved
 * from the retired Home v2: PR-2 (the next step), PP-3 (roles with days left) and ST-4 (the
 * story counts). Profile (PS-2, PS-6 mute) is in ProfileV2.test.tsx.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { gapApi } from "../../api/gap";
import { jobTargetsApi, resumesApi } from "../../api/inputs";
import { AppRoutes, createQueryClient } from "../../App";
import { EMPTY_PROFILE } from "../../mocks/handlers";
import { mockStore } from "../../mocks/node";
import { mockStory, resetMockStories } from "../../mocks/storyHandlers";
import { setFeatureOverrides } from "../../theme/features";
import { greeting } from "./HomeStrova";

const USER_ID = "00000000-0000-4000-8000-0000000000a1";
const EMAIL = "ana@example.com";

function signIn(style: "weekly" | "checklist") {
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
  mockStore.db.profiles[EMAIL] = { ...EMPTY_PROFILE, full_name: "Ana Lopez", plan_style: style };
}

beforeEach(() => setFeatureOverrides({ v2_enabled: true }));
afterEach(() => setFeatureOverrides({}));

function renderHome() {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <AppRoutes />
        <Routes>
          <Route path="*" element={null} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

async function roleWithBehavioral(dateInDays: number | null = null) {
  const form = new FormData();
  form.append("text", "Backend engineer, Python and Go.\n\nEngineer, Shoply, 2021 to now\n- Built the refunds API\n");
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  const { job_target: created } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  const job = await jobTargetsApi.get(created.id);
  await fetch(`${location.origin}/api/roles/${job.id}/interviews`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ interview_types: ["behavioral"] }),
  });
  await gapApi.start(job.id, { resume_id: resume.id });
  if (dateInDays !== null)
    mockStore.db.interviewDates = { [job.id]: new Date(Date.now() + dateInDays * 86_400_000).toISOString().slice(0, 10) };
  return job;
}

describe("Home with Strova", () => {
  it("HO-1: the greeting by time of day", () => {
    expect(greeting(new Date(2026, 9, 30, 9))).toBe("Good morning");
    expect(greeting(new Date(2026, 9, 30, 14))).toBe("Good afternoon");
    expect(greeting(new Date(2026, 9, 30, 20))).toBe("Good evening");
  });

  it("HO-1, PR-2: the greeting, Strova's next step from the plan, the plan, the four summary cards, no suggestion lists", async () => {
    signIn("weekly");
    const job = await roleWithBehavioral();
    renderHome();
    expect(await screen.findByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening), Ana$/ })).toBeInTheDocument();
    const hero = await screen.findByRole("region", { name: "Strova's next step" });
    expect(within(hero).getByRole("img", { name: "Strova is coaching" })).toHaveAttribute("width", "104");
    expect(hero).toHaveTextContent(/Rehearse .* · Behavioral\./);
    expect(within(hero).getByRole("link", { name: "Start the take" })).toHaveAttribute("href", expect.stringMatching(/^\/interviews\//));
    expect(within(hero).getByRole("link", { name: /^Open / })).toHaveAttribute("href", `/roles/${job.id}`);
    expect(screen.getByTestId("weekly-plan")).toBeInTheDocument();
    const cards = screen.getByRole("region", { name: "Summary" });
    expect(within(cards).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      expect.stringMatching(/^\/resumes/),
      "/roles",
      "/rehearsals",
      "/stories",
    ]);
    expect(screen.queryByText(/Strova suggests/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
  });

  it("PS-4: the weekly plan shows the week, a chip legend, one item a day, and today's item highlighted with its action", async () => {
    signIn("weekly");
    await roleWithBehavioral();
    renderHome();
    const plan = await screen.findByTestId("weekly-plan");
    expect(within(plan).getByRole("heading", { name: "This week's plan" })).toBeInTheDocument();
    expect(plan).toHaveTextContent(/[A-Z][a-z]{2} \d+ to [A-Z][a-z]{2} \d+ · Change style/);
    const legend = within(plan).getByLabelText("Legend");
    expect(legend).toHaveTextContent("Rehearsalmock interviewsStorystory goalsResumeResume issues");
    const rows = within(plan).getAllByTestId("plan-item");
    const days = rows.map((r) => r.querySelector(".home-planitem__day")?.textContent);
    expect(new Set(days).size).toBe(days.length);
    expect(rows.length).toBeLessThanOrEqual(6);
    const today = new Date().getDay();
    if (today !== 0) {
      const current = rows.find((r) => r.getAttribute("aria-current") === "step") as HTMLElement;
      expect(current).toHaveTextContent("Today");
      expect(within(current).getByRole("link", { name: "Start the take" })).toBeInTheDocument();
    }
  });

  it("PS-3: the checklist has three groups, collapsed, each with chip, title, X of Y done, progress and status", async () => {
    signIn("checklist");
    resetMockStories([mockStory({ id: "s1", title: "Checkout", skills: ["ownership"], status: "proven" })]);
    await roleWithBehavioral();
    const user = renderHome();
    const plan = await screen.findByTestId("checklist-plan");
    expect(within(plan).getByRole("heading", { name: "Your readiness checklist" })).toBeInTheDocument();
    const groups = ["rehearsal", "story", "resume"].map((k) => within(plan).getByTestId(`group-${k}`));
    for (const g of groups) expect(g).not.toHaveAttribute("open");
    expect(groups[0]).toHaveTextContent("Rehearsal");
    expect(groups[0]).toHaveTextContent("0 of 1 done");
    expect(groups[0]).toHaveTextContent(/Next: .* · Behavioral: readiness 75 or more, Not started · 1 open/);
    // Six story skills (one Proven) and two story ideas from the resume.
    expect(groups[1]).toHaveTextContent("1 of 8 done");
    expect(within(groups[1]).getByRole("progressbar", { name: "Story completion progress" })).toHaveAttribute("aria-valuenow", "13");
    await user.click(within(groups[0]).getByText("Rehearsals"));
    expect(groups[0]).toHaveAttribute("open");
    const next = within(groups[0]).getByRole("listitem");
    expect(next).toHaveAttribute("aria-current", "step");
    expect(within(next).getByRole("link", { name: "Start the take" })).toBeInTheDocument();
  });

  it("PS-5: before any role, no rehearsal items; the next step is a story or resume item", async () => {
    signIn("checklist");
    const form = new FormData();
    form.append("text", "Backend engineer.\n\nEngineer, Shoply, 2021 to now\n- Built the refunds API\n");
    await resumesApi.upload(form);
    renderHome();
    const plan = await screen.findByTestId("checklist-plan");
    expect(within(plan).getByTestId("group-rehearsal")).toHaveTextContent("0 of 0 done");
    expect(within(plan).getByTestId("group-rehearsal")).toHaveTextContent("Added when you add a target role");
    const hero = screen.getByRole("region", { name: "Strova's next step" });
    expect(hero).not.toHaveTextContent("Rehearse");
  });

  it("PP-3, ST-4: the roles card lists roles with days left; the stories card counts by status", async () => {
    signIn("weekly");
    resetMockStories([
      mockStory({ id: "s1", title: "Checkout", skills: ["ownership"], status: "proven" }),
      mockStory({ id: "s2", title: "Pushback", skills: ["conflict_handling"] }),
    ]);
    await roleWithBehavioral(6);
    renderHome();
    const roles = await screen.findByTestId("roles-card");
    expect(await within(roles).findByText("1 role")).toBeInTheDocument();
    expect(roles).toHaveTextContent(/ · 6 days$/);
    const stories = screen.getByTestId("stories-card");
    expect(await within(stories).findByText("2 stories")).toBeInTheDocument();
    expect(stories).toHaveTextContent("1 Proven · 1 Draft");
  });
});
