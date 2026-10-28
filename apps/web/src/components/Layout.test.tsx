/** UI-2: the left rail nav. "Stories" and the v2 labels show only when `v2_enabled` is on. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { createQueryClient } from "../App";
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

  it("UI-2: shows Home, Stories, Interviews, Questions and Account when v2_enabled is on", () => {
    setFeatureOverrides({ v2_enabled: true });
    const nav = renderNav();
    const main = within(nav).getAllByRole("list")[0];
    const labels = within(main)
      .getAllByRole("link")
      .map((a) => a.textContent)
      .filter((t) => !t?.includes("(dev)"));
    expect(labels).toEqual(["Home", "Stories", "Interviews", "Questions", "Account"]);
    expect(within(nav).getByRole("link", { name: "Stories" })).toHaveAttribute("href", "/stories");
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
