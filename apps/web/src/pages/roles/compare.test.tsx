/**
 * Resume comparison (RC-1 to RC-8) on Add a target role and the role page, against the MSW
 * mocks (src/mocks/compareHandlers.ts): the newest non-main resume fits best.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "../../api/inputs";
import { AppRoutes, createQueryClient } from "../../App";
import { EMPTY_PROFILE } from "../../mocks/handlers";
import { mockStore } from "../../mocks/node";
import { setFeatureOverrides } from "../../theme/features";

const USER_ID = "00000000-0000-4000-8000-0000000000a1";
const EMAIL = "ana@example.com";

function Where() {
  const { pathname } = useLocation();
  return <span data-testid="where">{pathname}</span>;
}

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
  mockStore.db.profiles[EMAIL] = { ...EMPTY_PROFILE, plan_style: "weekly", target_level: "senior" };
  setFeatureOverrides({ v2_enabled: true });
});
afterEach(() => setFeatureOverrides({}));

function renderApp(path: string) {
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

async function addResume(text: string) {
  const form = new FormData();
  form.append("text", text);
  const { resume } = await resumesApi.upload(form);
  return resumesApi.get(resume.id);
}

async function toInterviewsStep(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "paste the text" }));
  await user.click(screen.getByRole("textbox", { name: "Job posting text" }));
  await user.paste("Senior engineer, payments. ".repeat(10));
  await user.click(screen.getByRole("button", { name: "Read the posting" }));
  await screen.findByRole("textbox", { name: "Company" }, { timeout: 4000 });
  await user.click(screen.getByRole("button", { name: "Looks right" }));
  await screen.findByRole("checkbox", { name: /Behavioral/ }, { timeout: 4000 });
}

describe("resume comparison", () => {
  it("RC-1: with one resume, Add a target role offers no comparison", async () => {
    await addResume("Backend engineer, Python and Go.");
    const user = renderApp("/roles/new");
    await toInterviewsStep(user);
    expect(screen.queryByRole("button", { name: "Compare my resumes" })).toBeNull();
  });

  it("RC-1, RC-3, RC-6: on Add a target role, compare, then Use this one picks the resume the role is created with", async () => {
    const main = await addResume("Backend engineer, Python and Go. Led the move to PostgreSQL.");
    const other = await addResume("Platform engineer, Kafka and Go. Ran the event pipeline.");
    const user = renderApp("/roles/new");
    await toInterviewsStep(user);
    expect(screen.getByText(/Measured against:/)).toHaveTextContent(main.name ?? "");
    // Nothing runs until the user asks (RC-1).
    await user.click(screen.getByRole("button", { name: "Compare my resumes" }));
    const panel = screen.getByRole("region", { name: "Which resume fits this role best" });
    await user.click(within(panel).getByRole("button", { name: "Compare my resumes" }));
    // RC-3: the pick and its reason, from the data.
    expect(await within(panel).findByTestId("comparison-reason")).toHaveTextContent(`${other.name} fits best`);
    const rows = within(panel).getAllByTestId("compared-resume");
    expect(rows[0]).toHaveTextContent("Best fit");
    expect(rows[0]).toHaveTextContent(other.name ?? "");
    expect(rows[1]).toHaveTextContent("In use");
    // RC-6: nothing switched yet; the user's click does it.
    expect(screen.getByText(/Measured against:/)).toHaveTextContent(main.name ?? "");
    await user.click(within(rows[0]).getByRole("button", { name: "Use this one" }));
    expect(screen.getByText(/Measured against:/)).toHaveTextContent(other.name ?? "");
    await user.click(screen.getByRole("button", { name: "Create the role" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toMatch(/^\/roles\/(?!new$)[^/]+$/), {
      timeout: 4000,
    });
    const resumesUsed = new Set((mockStore.db.interviews ?? []).map((i) => i.resume_id));
    expect(resumesUsed).toEqual(new Set([other.id]));
  });

  it("RC-4, RC-5, RC-6, RC-8: the role page compares on demand, adds a covered line, offers a story for the rest and moves the role", async () => {
    const main = await addResume("Backend engineer, Python and Go. Led the move to PostgreSQL.");
    const other = await addResume("Platform engineer, Kafka and Go. Ran the event pipeline.");
    const { job_target: created } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
    const job = await jobTargetsApi.get(created.id);
    await fetch(`${location.origin}/api/roles/${job.id}/interviews`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ interview_types: ["behavioral"] }),
    });
    const user = renderApp(`/roles/${job.id}`);
    const card = await screen.findByTestId("compare-resumes");
    expect(card).toHaveTextContent("Compare your resumes for this role");
    await user.click(within(card).getByRole("button", { name: "Compare my resumes" }));
    await user.click(await within(card).findByRole("button", { name: "Compare my resumes" }));
    // RC-8: saved on the role, summarized in one line.
    await waitFor(() => expect(card).toHaveTextContent(`Compared 2 resumes`));
    expect(card).toHaveTextContent(`${other.name} fit best`);

    // RC-4: the gap the main resume covers names it and its line; Add to resume copies it.
    const gaps = within(card).getAllByTestId("comparison-gap");
    const covered = gaps.find((g) => g.textContent?.includes("Kafka is not shown")) as HTMLElement;
    expect(covered).toHaveTextContent(`Your ${main.name} resume shows this: “Kafka”`);
    await user.click(within(covered).getByRole("button", { name: "Add to resume" }));
    await waitFor(() => expect(covered).toHaveTextContent(`Added to ${other.name}`));
    expect(within(covered).queryByRole("button", { name: "Add to resume" })).toBeNull();

    // RC-5: a gap no resume covers opens a coach session for the role with the gap.
    const uncovered = gaps.find((g) => g.textContent?.includes("No payments experience")) as HTMLElement;
    expect(uncovered).toHaveTextContent("None of your resumes shows this.");
    const craft = within(uncovered).getByRole("link", { name: "Craft a story" });
    const href = new URL(craft.getAttribute("href") ?? "", "http://x");
    expect(href.pathname).toBe("/coach/new");
    expect(href.searchParams.get("job")).toBe(job.id);
    expect(href.searchParams.get("ask")).toContain("Payments or financial systems");

    // RC-6: Use this one moves the role to the recommended resume.
    const best = within(card).getAllByTestId("compared-resume")[0];
    await user.click(within(best).getByRole("button", { name: "Use this one" }));
    await waitFor(() => expect(within(card).getAllByTestId("compared-resume")[0]).toHaveTextContent("In use"));
  });

  it("RC-4: Dismiss hides a covered hint", async () => {
    await addResume("Backend engineer, Python and Go.");
    await addResume("Platform engineer, Kafka and Go.");
    const { job_target: created } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
    const user = renderApp(`/roles/${created.id}`);
    const card = await screen.findByTestId("compare-resumes");
    await user.click(within(card).getByRole("button", { name: "Compare my resumes" }));
    await user.click(await within(card).findByRole("button", { name: "Compare my resumes" }));
    await within(card).findByTestId("comparison-reason");
    expect(within(card).getAllByTestId("comparison-gap")).toHaveLength(2);
    await user.click(within(card).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(within(card).getAllByTestId("comparison-gap")).toHaveLength(1));
  });
});
