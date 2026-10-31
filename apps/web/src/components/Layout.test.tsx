/** UI-2, NV-1, NV-3, SV-7: the left rail nav and the top bar. The v2 items show only when `v2_enabled` is on. */
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
import { RailNav, resumesLabel } from "./Layout";

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

function signIn(fullName: string | null) {
  const email = "ana@example.com";
  mockStore.db.users[email] = {
    id: "u1",
    org_id: "o1",
    email,
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: fullName,
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
}

describe("UI-2 left rail nav", () => {
  it("UI-2: hides Stories and keeps the v1 menu when v2_enabled is off", () => {
    const nav = renderNav();
    expect(within(nav).queryByRole("link", { name: "Stories" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Interview rehearsals" })).toHaveAttribute("href", "/");
    expect(within(nav).getByRole("link", { name: "Resumes" })).toHaveAttribute("href", "/resumes");
  });

  it("NV-1: shows exactly Home, {First name}'s Resumes, Target roles, Rehearsals with Strova and Career Stories with Strova, in that order", async () => {
    setFeatureOverrides({ v2_enabled: true });
    signIn("Ana Lopez");
    const nav = renderNav();
    expect(await within(nav).findByRole("link", { name: "Ana's Resumes" })).toHaveAttribute("href", "/resumes");
    const labels = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(labels).toEqual(["Home", "Ana's Resumes", "Target roles", "Rehearsals with Strova", "Career Stories with Strova"]);
    expect(within(nav).getByRole("link", { name: "Target roles" })).toHaveAttribute("href", "/roles");
    expect(within(nav).getByRole("link", { name: "Rehearsals with Strova" })).toHaveAttribute("href", "/rehearsals");
    expect(within(nav).getByRole("link", { name: "Career Stories with Strova" })).toHaveAttribute("href", "/stories");
    // No Strova icons in the rail: the Rehearsals and Career Stories pages carry her in their headers.
    expect(nav.querySelectorAll("svg")).toHaveLength(0);
    // No separate coach button, and the dev text interview stays in the account menu.
    expect(screen.queryByRole("link", { name: "Talk to your coach" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: /Text interview/ })).not.toBeInTheDocument();
  });

  it("NV-1: the resumes item says Your resumes when the profile has no name", async () => {
    setFeatureOverrides({ v2_enabled: true });
    signIn(null);
    const nav = renderNav();
    expect(await within(nav).findByRole("link", { name: "Your resumes" })).toHaveAttribute("href", "/resumes");
    expect(resumesLabel("  Sara  Ali ")).toBe("Sara's Resumes");
    expect(resumesLabel("")).toBe("Your resumes");
  });

  it("NV-3: Question bank and Progress are not in the v2 rail", () => {
    setFeatureOverrides({ v2_enabled: true });
    const nav = renderNav();
    expect(within(nav).queryByRole("link", { name: /Question bank/ })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Progress" })).toBeNull();
  });

  it("NV-1: marks Career Stories current on story and coach pages", () => {
    setFeatureOverrides({ v2_enabled: true });
    const nav = renderNav("/coach/abc");
    expect(within(nav).getByRole("link", { name: "Career Stories with Strova" })).toHaveAttribute("aria-current", "page");
  });

  it("NV-1: marks Rehearsals current on interview and take pages, and Target roles on job pages", () => {
    setFeatureOverrides({ v2_enabled: true });
    let nav = renderNav("/sessions/abc/debrief");
    expect(within(nav).getByRole("link", { name: "Rehearsals with Strova" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
    cleanup();
    nav = renderNav("/jobs/j1/confirm");
    expect(within(nav).getByRole("link", { name: "Target roles" })).toHaveAttribute("aria-current", "page");
  });
});

describe("FL-1 v2 flag from GET /status", () => {
  it("FL-1: shows the v2 nav when GET /status says v2_enabled is on", async () => {
    mockStore.db.siteStatus = { ...mockStore.db.siteStatus, v2_enabled: true };
    const nav = renderNav();
    expect(await within(nav).findByRole("link", { name: "Career Stories with Strova" })).toHaveAttribute("href", "/stories");
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

describe("SV-7, NV-3 v2 top bar and old routes", () => {
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

  function renderShell(v2: boolean, path = "/reports") {
    signedIn();
    setFeatureOverrides({ v2_enabled: v2 });
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

  it("SV-7: the v2 top bar has the lockup with the Strong Hire logo, the usage pill and the initials button that opens Profile", async () => {
    const user = renderShell(true);
    const bar = await screen.findByRole("banner", { name: "Top bar" });
    const brand = within(bar).getByRole("link", { name: "Strong Hire with Strova, home" });
    // The existing logo, never a Strova avatar or mark.
    expect(within(brand).getByRole("img", { name: "Strong Hire" })).toBeInTheDocument();
    expect(brand.querySelector(".strova")).toBeNull();
    expect(brand).toHaveTextContent("Strong Hirewith Strova");
    expect(within(brand).getByText("with Strova")).toHaveClass("brand__with");
    expect(await within(bar).findByText(/Monthly plan · 78 of 120 minutes left/)).toBeInTheDocument();
    // The mockup's top bar has no greeting and no bell.
    expect(within(bar).queryByRole("button", { name: /^Updates/ })).toBeNull();
    expect(screen.queryByText(/Let's get you ready/)).toBeNull();
    // The old rail meter and rail account menu are gone.
    expect(screen.queryByText("Interview minutes")).toBeNull();
    const initials = within(bar).getByRole("button", { name: "Account menu" });
    expect(initials).toHaveTextContent("AL");
    await user.click(initials);
    const menu = initials.nextElementSibling as HTMLElement;
    const links = within(menu)
      .getAllByRole("link")
      .map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links.slice(0, 4)).toEqual([
      ["Profile", "/account/profile"],
      ["Account", "/account"],
      ["Plan and billing", "/account#plan"],
      ["Reports", "/reports"],
    ]);
    expect(within(menu).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    await user.click(within(menu).getByRole("link", { name: "Profile" }));
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
  });

  it("NV-3: the Question bank and Progress routes still render with v2 on", async () => {
    renderShell(true, "/questions");
    expect(await screen.findByRole("heading", { level: 1, name: "Question bank" })).toBeInTheDocument();
    cleanup();
    renderShell(true, "/reports");
    expect(await screen.findByRole("heading", { level: 1, name: "Progress" })).toBeInTheDocument();
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

describe("SV-6 live room frame", () => {
  function renderApp(path: string) {
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("SV-6: with v2 the live room is full bleed, without the slim app header", async () => {
    setFeatureOverrides({ v2_enabled: true });
    signIn("Ana Lopez");
    renderApp("/sessions/s-missing/live");
    expect(await screen.findByRole("main")).toBeInTheDocument();
    expect(screen.queryByText("Live interview")).not.toBeInTheDocument();
  });

  it("SV-6, FL-1: with v2 off the room keeps the slim header", async () => {
    signIn("Ana Lopez");
    renderApp("/sessions/s-missing/live");
    expect(await screen.findByText("Live interview")).toBeInTheDocument();
  });
});
