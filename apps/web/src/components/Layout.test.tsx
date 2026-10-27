/** UI-2: the left rail nav. "Stories" and the v2 labels show only when `v2_enabled` is on. */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { setFeatureOverrides } from "../theme/features";
import { RailNav } from "./Layout";

function renderNav(path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <RailNav />
    </MemoryRouter>,
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
