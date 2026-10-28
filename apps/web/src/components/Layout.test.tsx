/** UI-2: the left rail nav. "Stories" and the v2 labels show only when `v2_enabled` is on. */
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
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

  it("UI-2: shows Home, Resumes, Interviews, Stories, Question bank and Progress, in that order, when v2_enabled is on", () => {
    setFeatureOverrides({ v2_enabled: true });
    const nav = renderNav();
    const labels = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(labels).toEqual(["Home", "Resumes", "Interviews", "Stories", "Question bankNew", "Progress"]);
    expect(within(nav).getByRole("link", { name: /Question bank/ })).toHaveAttribute("href", "/questions");
    expect(within(nav).getByRole("link", { name: "Resumes" })).toHaveAttribute("href", "/resumes");
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

  it("UI-2: v2 has a top bar (plan chip, updates, avatar menu); the rail keeps the menu and Talk to your coach", async () => {
    const user = renderShell(true);
    const bar = await screen.findByRole("banner", { name: "Top bar" });
    expect(await within(bar).findByText(/Monthly plan · 78 of 120 minutes left/)).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: /^Updates/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Talk to your coach" })).toHaveAttribute("href", "/coach/new");
    // The old rail meter and rail account menu are gone.
    expect(screen.queryByText("Interview minutes")).toBeNull();
    await user.click(within(bar).getByRole("button", { name: "Account menu" }));
    const menu = within(bar).getByRole("button", { name: "Account menu" }).nextElementSibling as HTMLElement;
    const links = within(menu)
      .getAllByRole("link")
      .map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links.slice(0, 3)).toEqual([
      ["Account", "/account"],
      ["Plan and billing", "/account#plan"],
      ["Reports", "/reports"],
    ]);
    expect(within(menu).queryByRole("link", { name: "Questions" })).toBeNull();
    expect(within(menu).queryByRole("link", { name: "Resumes" })).toBeNull();
    expect(within(menu).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("UI-2: the greeting shows on the first visit only", async () => {
    globalThis.localStorage?.clear();
    renderShell(true);
    expect(await screen.findByText("Welcome, Ana. Let's get you ready.")).toBeInTheDocument();
    cleanup();
    renderShell(true);
    await screen.findByRole("banner", { name: "Top bar" });
    expect(screen.queryByText(/Let's get you ready/)).toBeNull();
  });

  it("UI-2: the bell shows a dot until it is opened, with the site banner and what's new", async () => {
    globalThis.localStorage?.clear();
    mockStore.db.siteStatus = {
      ...mockStore.db.siteStatus,
      banner: { text: "Maintenance Sunday 02:00 UTC", severity: "info", until: "2099-01-01T00:00:00Z" },
    };
    const user = renderShell(true);
    const bell = await screen.findByRole("button", { name: /^Updates, \d+ new$/ });
    await user.click(bell);
    const panel = screen.getByRole("region", { name: "Updates" });
    expect(within(panel).getByText("Maintenance Sunday 02:00 UTC")).toBeInTheDocument();
    expect(within(panel).getByText("New: Question bank")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Updates" })).toBeInTheDocument();
    mockStore.db.siteStatus = { ...mockStore.db.siteStatus, banner: null };
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
