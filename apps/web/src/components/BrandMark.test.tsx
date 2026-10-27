/** The v2 mark is an ink rounded square with a check (UI-1), and the slogan stays hidden until it is agreed. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hasSlogan, SLOGAN } from "../labels";
import { BrandMark, CheckBadge } from "./BrandMark";

describe("BrandMark", () => {
  it("UI-1: draws a rounded square in the mark color with a check cut in the background color", () => {
    const { container } = render(<BrandMark />);
    expect(screen.getByRole("img", { name: "Strong Hire" })).toHaveAttribute("data-tone", "light");
    expect(container.querySelector('rect[fill="var(--brand-main)"]')).toHaveAttribute("rx", "7");
    expect(container.querySelector('path[stroke="var(--brand-bg)"]')).not.toBeNull();
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
