/** UI-2: the left rail nav. "Stories" and the v2 labels show only when `v2_enabled` is on. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { refreshUsage } from "../mocks/handlers";
import { mockStore, server } from "../mocks/node";
import { setFeatureOverrides } from "../theme/features";
import { RailNav } from "./Layout";

function renderNav(path = "/") {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <RailNav />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return screen.getByRole("navigation", { name: "Main" });
}

afterEach(() => setFeatureOverrides({}));

describe("UI-2 left rail nav", () => {
  it("UI-2: hides Stories and keeps the v1 menu when v2_enabled is off", () => {
    const nav = renderNav();
    expect(within(nav).queryByRole("link", { name: "Stories" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Interview rehearsals" })).toHaveAttribute("href", "/");
    expect(within(nav).getByRole("link", { name: "Resumes" })).toHaveAttribute("href", "/resumes");
  });

  it("UI-2: shows the canvas rail, Home, Stories (A), Interviews (B) and Progress, when v2_enabled is on", () => {
    setFeatureOverrides({ v2_enabled: true });
    const nav = renderNav();
    const labels = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(labels).toEqual(["Home", "StoriesA", "InterviewsB", "Progress"]);
    expect(within(nav).getByRole("link", { name: "Stories" })).toHaveAttribute("href", "/stories");
    expect(within(nav).getByRole("link", { name: "Interviews" })).toHaveAttribute("href", "/jobs");
    expect(within(nav).getByRole("link", { name: "Progress" })).toHaveAttribute("href", "/reports");
    // The dev text interview moved to the account menu.
    expect(within(nav).queryByRole("link", { name: /Text interview/ })).not.toBeInTheDocument();
  });

  it("UI-2: marks Stories current on story and coach pages", () => {
    setFeatureOverrides({ v2_enabled: true });
    const nav = renderNav("/coach/abc");
    expect(within(nav).getByRole("link", { name: "Stories" })).toHaveAttribute("aria-current", "page");
  });

  it("UI-2: marks Interviews current on interview pages", () => {
    setFeatureOverrides({ v2_enabled: true });
    const nav = renderNav("/sessions/abc/debrief");
    expect(within(nav).getByRole("link", { name: "Interviews" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });
});

describe("FL-1 v2 flag from GET /status", () => {
  it("FL-1: shows the v2 nav when GET /status says v2_enabled is on", async () => {
    mockStore.db.siteStatus = { ...mockStore.db.siteStatus, v2_enabled: true };
    const nav = renderNav();
    expect(await within(nav).findByRole("link", { name: "Stories" })).toHaveAttribute("href", "/stories");
  });

  it("FL-1: keeps the v1 nav when GET /status says v2_enabled is off", async () => {
    mockStore.db.siteStatus = { ...mockStore.db.siteStatus, v2_enabled: false };
    const nav = renderNav();
    // Wait for the status to load: the v1 menu stays.
    await new Promise((r) => setTimeout(r, 50));
    expect(within(nav).queryByRole("link", { name: "Stories" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Interview rehearsals" })).toBeInTheDocument();
  });

  it("FL-1: the flag is off while GET /status loads and when it fails", async () => {
    server.use(http.get("*/status", () => HttpResponse.json({ detail: "down" }, { status: 500 })));
    const nav = renderNav();
    expect(within(nav).queryByRole("link", { name: "Stories" })).not.toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(within(nav).queryByRole("link", { name: "Stories" })).not.toBeInTheDocument();
  });

  it("FL-1: an override wins over GET /status", async () => {
    mockStore.db.siteStatus = { ...mockStore.db.siteStatus, v2_enabled: true };
    setFeatureOverrides({ v2_enabled: false });
    const nav = renderNav();
    await new Promise((r) => setTimeout(r, 50));
    expect(within(nav).queryByRole("link", { name: "Stories" })).not.toBeInTheDocument();
  });
});

describe("UI-2 v2 rail footer and account menu", () => {
  function signedIn() {
    const email = "ana@example.com";
    mockStore.db.users[email] = {
      id: "u1",
      org_id: "o1",
      email,
      auth_provider: "dev",
      training_consent: false,
      created_at: "2026-10-01T10:00:00Z",
      full_name: "Ana Lopez",
      profile_complete: true,
    };
    mockStore.db.auth = { status: "signed_in", email, userEmail: email };
    mockStore.db.usage = refreshUsage({ ...mockStore.db.usage, plan: "paid", minutes_used: 42, minutes_cap: 120 });
  }

  function renderShell(v2: boolean) {
    signedIn();
    setFeatureOverrides({ v2_enabled: v2 });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={["/reports"]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    return user;
  }

  it("UI-2: v2 has Talk to your coach, the interview minutes, and Questions, Resumes and Account in the account menu", async () => {
    const user = renderShell(true);
    expect(await screen.findByRole("link", { name: "Talk to your coach" })).toHaveAttribute("href", "/coach/new");
    expect(await screen.findByText("Interview minutes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Account menu" }));
    expect(screen.getByRole("link", { name: "Questions" })).toHaveAttribute("href", "/questions");
    expect(screen.getByRole("link", { name: "Resumes" })).toHaveAttribute("href", "/resumes");
    expect(screen.getByRole("link", { name: "Account" })).toHaveAttribute("href", "/account");
  });

  it("FL-1: v1 keeps its rail footer, with no coach button", async () => {
    const user = renderShell(false);
    expect(await screen.findByText("Minutes")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Talk to your coach" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Account menu" }));
    const menu = screen.getByRole("button", { name: "Account menu" }).nextElementSibling as HTMLElement;
    expect(within(menu).getAllByRole("link").map((a) => a.textContent)).toEqual(["Account"]);
  });
});
