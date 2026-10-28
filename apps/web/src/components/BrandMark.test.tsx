/** The Approved h logo keeps its four parts in every tone (UI-1), and the slogan stays hidden until it is agreed. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hasSlogan, SLOGAN } from "../labels";
import { BrandMark, CheckBadge } from "./BrandMark";

describe("BrandMark", () => {
  it.each(["light", "stage", "dark"] as const)(
    "UI-1: the %s tone draws the lamp, the amber light, the chair-h cut out of it, and the green check",
    (tone) => {
      const { container } = render(<BrandMark tone={tone} />);
      const svg = screen.getByRole("img", { name: "Strong Hire" });
      const parts = [...svg.querySelectorAll("[data-part]")].map((el) => el.getAttribute("data-part"));
      // In this order: the chair after the light, so it is a cut-out, never ink on top.
      expect(parts).toEqual(["lamp", "light", "chair", "check"]);
      expect(container.querySelector('[data-part="light"]')).toHaveAttribute("fill", "var(--brand-light)");
      const chair = [...container.querySelectorAll('[data-part="chair"] > *')];
      expect(chair.length).toBe(2);
      for (const piece of chair) expect(piece).toHaveAttribute("fill", "var(--brand-cut)");
      expect(container.querySelector('[data-part="check"] circle[fill="var(--brand-check)"]')).not.toBeNull();
      expect(container.querySelector('[data-part="check"] path[stroke="#ffffff"]')).not.toBeNull();
    },
  );

  it("UI-1: never colors the light green; the light and the check use different colors", () => {
    const { container } = render(<BrandMark />);
    expect(container.querySelector('[data-part="light"]')?.getAttribute("fill")).not.toBe(
      container.querySelector('[data-part="check"] circle:last-of-type')?.getAttribute("fill"),
    );
  });

  it("the v1 stage tone draws as the light tone; the dark tone is for the live room", () => {
    const { rerender } = render(<BrandMark tone="stage" />);
    expect(screen.getByRole("img", { name: "Strong Hire" })).toHaveAttribute("data-tone", "light");
    rerender(<BrandMark tone="dark" />);
    expect(screen.getByRole("img", { name: "Strong Hire" })).toHaveAttribute("data-tone", "dark");
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
