/** The Approved h logo keeps its four parts, and the slogan stays hidden until it is agreed. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hasSlogan, SLOGAN } from "../labels";
import { BrandMark, CheckBadge } from "./BrandMark";

describe("BrandMark", () => {
  it("draws the lamp, the amber light, the chair-h cut out of the light, and the green check", () => {
    const { container } = render(<BrandMark tone="stage" />);
    expect(screen.getByRole("img", { name: "Strong Hire" })).toHaveAttribute("data-tone", "stage");
    const light = container.querySelector('path[fill="var(--light)"]');
    expect(light).not.toBeNull();
    // The chair is drawn in the background color, after the light: a cut-out, never on top in ink.
    expect(container.querySelectorAll('[fill="var(--brand-bg)"]').length).toBeGreaterThanOrEqual(3);
    expect(container.querySelector('circle[fill="var(--ok)"]')).not.toBeNull();
  });

  it("the check badge is decorative; the verdict word carries the meaning", () => {
    const { container } = render(<CheckBadge />);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("slogan", () => {
  it("is a placeholder until it is agreed, and the placeholder is not shown", () => {
    expect(SLOGAN).toBe("{{SLOGAN}}");
    expect(hasSlogan(SLOGAN)).toBe(false);
    expect(hasSlogan("A real line")).toBe(true);
  });
});
