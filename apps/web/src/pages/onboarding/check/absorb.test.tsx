/**
 * RSD-6, RSD-11, RSD-12, RSD-14 (and RM-3, RM-4, SG-6, moved here from the retired resume detail
 * page): the check page absorbs the detail page. Stories, resume lines and the three drawers, and
 * `/resumes/:id` redirects to the check page. Runs with v2 on against the MSW mocks.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { jobTargetsApi, resumesApi } from "../../../api/inputs";
import { AppRoutes, createQueryClient } from "../../../App";
import { mockStore, server } from "../../../mocks/node";
import { setFeatureOverrides } from "../../../theme/features";
import { NO_REWRITES } from "./LinesStep";
import { craftFromIdeaPath } from "./StoriesStep";

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

async function addResume() {
  const form = new FormData();
  form.append("text", "Backend engineer, seven years of Python.");
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  return mockStore.db.resumes.find((r) => r.id === resume.id)!;
}

/** A role whose interview uses this resume. */
async function roleOn(resumeId: string) {
  const { job_target: created } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  const job = await jobTargetsApi.get(created.id);
  await fetch(`${location.origin}/api/roles/${job.id}/interviews`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ interview_types: ["behavioral"], resume_id: resumeId }),
  });
  return job;
}

function Where() {
  const { pathname, search } = useLocation();
  return <span data-testid="where">{pathname + search}</span>;
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

describe("RSD-6: one resume page", () => {
  it("RSD-6: /resumes/:id redirects to /resumes/:id/check and keeps its query", async () => {
    const r = await addResume();
    renderAt(`/resumes/${r.id}?step=stories&from=email`);
    await ready();
    expect(screen.getByTestId("where")).toHaveTextContent(`/resumes/${r.id}/check?step=stories&from=email`);
    expect(screen.getByRole("button", { name: /Stories to tell/ })).toHaveAttribute("aria-current", "step");
  });

  it("RSD-6: Home and What first link to the check page", async () => {
    const r = await addResume();
    if (mockStore.db.profiles[EMAIL]) mockStore.db.profiles[EMAIL].plan_style = "weekly";
    else mockStore.db.profiles[EMAIL] = { ...(await import("../../../mocks/handlers")).EMPTY_PROFILE, plan_style: "weekly" };
    renderAt("/");
    const links = await screen.findAllByRole("link");
    const toResume = await waitFor(() => {
      const found = links.filter((a) => a.getAttribute("href")?.startsWith(`/resumes/${r.id}`));
      expect(found.length).toBeGreaterThan(0);
      return found;
    });
    for (const a of toResume) expect(a.getAttribute("href")).toMatch(new RegExp(`^/resumes/${r.id}/check`));
  });
});

describe("RSD-11: stories to tell in interviews", () => {
  it("RSD-11, RM-3, RM-4: one idea at a time with skills, Still needs, Craft with Strova and Not a story (persists)", async () => {
    const r = await addResume();
    const user = renderAt(`/resumes/${r.id}/check?step=stories`);
    await ready();
    const view = await screen.findByTestId("stories-step");
    const card = await within(view).findByRole("article");
    const position = () => within(card).getByTestId("idea-position").textContent ?? "";
    expect(position()).toMatch(/^Story 1 of (\d+)$/);
    const total = Number(/of (\d+)/.exec(position())![1]);
    expect(within(card).getByText("Resume → Interview")).toBeInTheDocument();
    expect(within(card).getByText(/^Still needs: /)).toBeInTheDocument();
    const craft = within(card).getByRole("link", { name: "Craft with Strova" });
    expect(craft.getAttribute("href")).toMatch(/^\/coach\/new\?resume=/);
    expect(within(card).getByRole("button", { name: "Previous idea" })).toBeDisabled();
    const first = within(card).getByRole("heading").textContent;

    if (total > 1) {
      await user.click(within(card).getByRole("button", { name: "Next idea" }));
      expect(position()).toBe(`Story 2 of ${total}`);
      await user.click(within(card).getByRole("button", { name: "Previous idea" }));
    }
    await user.click(within(card).getByRole("button", { name: "Not a story" }));
    await waitFor(() => expect(within(view).queryByRole("heading", { name: first ?? "" })).not.toBeInTheDocument());
    // RM-4: the dismissal is stored, so the idea stays gone.
    const after = (await (await fetch(`${location.origin}/api/resumes/${r.id}/story-ideas`)).json()) as { ideas: unknown[] };
    expect(after.ideas).toHaveLength(total - 1);
    // The step count agrees (D-4).
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Stories to tell/ }).querySelector(".cvc-step__num")).toHaveTextContent(String(total - 1)),
    );
  });

  it("RSD-11: with every idea set aside it says so; Already crafted links each story", async () => {
    const r = await addResume();
    const ideas = (await (await fetch(`${location.origin}/api/resumes/${r.id}/story-ideas`)).json()) as {
      ideas: { resume_line_ref: string }[];
    };
    for (const i of ideas.ideas) await resumesApi.dismissIdea(r.id, i.resume_line_ref);
    renderAt(`/resumes/${r.id}/check?step=stories`);
    await ready();
    expect(await screen.findByText("No ideas left. Every achievement is a story or was set aside.")).toBeInTheDocument();
    expect(craftFromIdeaPath("r1", "roles[0].achievements[1]")).toBe("/coach/new?resume=r1&idea=roles%5B0%5D.achievements%5B1%5D");
  });
});

describe("RSD-12: stronger resume lines", () => {
  it("RSD-12, RM-3, SG-6: one rewrite with its story, the diff, Add to resume then Undo, and Dismiss; Add reloads the saved resume", async () => {
    const r = await addResume();
    const reads: string[] = [];
    const onStart = ({ request }: { request: Request }) => {
      if (request.method === "GET" && new URL(request.url).pathname === `/api/resumes/${r.id}`) reads.push(request.url);
    };
    server.events.on("request:start", onStart);
    try {
      const user = renderAt(`/resumes/${r.id}/check?step=lines`);
      await ready();
      const card = await screen.findByRole("region", { name: "Strova suggests a resume line" });
      expect(card).toHaveTextContent("Your stories → Resume");
      expect(card).toHaveTextContent(/^.*Line 1 of \d+/);
      await waitFor(() => expect(card).toHaveTextContent('your story "Checkout migration"'));
      expect(card.querySelector("del")?.textContent).toBe("Led checkout migration to new payments provider");
      expect(card.querySelector("ins")?.textContent).toMatch(/zero failed payments/);
      const before = reads.length;
      await user.click(within(card).getByRole("button", { name: "Add to resume" }));
      expect(await within(card).findByText("Added to your resume.")).toBeInTheDocument();
      await waitFor(() => expect(reads.length).toBeGreaterThan(before));
      await user.click(within(card).getByRole("button", { name: "Undo" }));
      await user.click(await within(card).findByRole("button", { name: "Dismiss" }));
      expect(await screen.findByText(NO_REWRITES)).toBeInTheDocument();
    } finally {
      server.events.removeListener("request:start", onStart);
    }
  });

  it("RSD-12: with none it says when Strova suggests one", () => {
    expect(NO_REWRITES).toBe("No rewrites yet. Strova suggests one when a story has a result your resume leaves out.");
  });
});

describe("RSD-14: the drawers", () => {
  it("RSD-14, RM-3: Used by N roles lists the roles with Open; Esc closes it and focus returns to the opener", async () => {
    const r = await addResume();
    const job = await roleOn(r.id);
    const user = renderAt(`/resumes/${r.id}/check`);
    await ready();
    const opener = await screen.findByTestId("used-by");
    expect(opener).toHaveTextContent("Used by 1 role");
    await user.click(opener);
    const drawer = screen.getByRole("dialog", { name: "Used by 1 role" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    const rows = within(drawer).getByRole("list", { name: "Roles that use this resume" });
    expect(within(rows).getAllByRole("listitem")).toHaveLength(1);
    expect(within(rows).getByText("No date yet")).toBeInTheDocument();
    expect(within(rows).getByRole("link", { name: /^Open / })).toHaveAttribute("href", `/roles/${job.id}`);
    expect(within(drawer).getByRole("link", { name: "Add a target role with this resume" })).toHaveAttribute(
      "href",
      `/roles/new?resume=${r.id}`,
    );
    expect(within(drawer).getByRole("button", { name: "Close" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Used by 1 role" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("RSD-14: focus is trapped in the drawer, and the close button and a backdrop click close it", async () => {
    const r = await addResume();
    await roleOn(r.id);
    const user = renderAt(`/resumes/${r.id}/check`);
    await ready();
    const opener = screen.getByRole("button", { name: "What Strova checks ›" });
    await user.click(opener);
    let drawer = screen.getByRole("dialog", { name: "What Strova checks" });
    expect(within(drawer).getByText(/gaps over 3 months/)).toBeInTheDocument();
    const close = within(drawer).getByRole("button", { name: "Close" });
    expect(close).toHaveFocus();
    // The only control: Tab and Shift+Tab stay on it.
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();
    await user.click(close);
    expect(screen.queryByRole("dialog", { name: "What Strova checks" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();

    await user.click(screen.getByRole("button", { name: /^1 role uses this resume ›$/ }));
    drawer = screen.getByRole("dialog", { name: "Used by 1 role" });
    const items = [...drawer.querySelectorAll<HTMLElement>("a[href], button")];
    items[items.length - 1].focus();
    await user.tab();
    expect(items[0]).toHaveFocus();
    // A click on the backdrop lands on the dialog element itself.
    await user.click(drawer);
    expect(screen.queryByRole("dialog", { name: "Used by 1 role" })).not.toBeInTheDocument();
  });

  it("RSD-14, IN-12: Findings you accepted lists each with its reason and Undo", async () => {
    const r = await addResume();
    r.accepted_issues = [{ key: "consistency.skills-missing:celery", accepted_at: "2026-10-28T10:00:00Z" }];
    const user = renderAt(`/resumes/${r.id}/check`);
    await ready();
    await user.click(screen.getByRole("button", { name: "Findings you accepted · 1 ›" }));
    const drawer = screen.getByRole("dialog", { name: "Findings you accepted · 1" });
    expect(within(drawer).getByText("✓ Accepted: A skill missing from Skills")).toBeInTheDocument();
    await user.click(within(drawer).getByRole("button", { name: "Undo accepting A skill missing from Skills" }));
    await waitFor(() => expect(r.accepted_issues).toEqual([]));
    expect(within(drawer).getByText("Nothing accepted yet.")).toBeInTheDocument();
  });
});
