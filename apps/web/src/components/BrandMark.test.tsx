/** The Orbit logo keeps its two parts in every tone (SV-10), and the slogan stays hidden until it is agreed. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hasSlogan, SLOGAN } from "../labels";
import { BrandMark, CheckBadge, ORBIT_DOT, ORBIT_RING } from "./BrandMark";

describe("BrandMark", () => {
  it.each(["light", "stage", "dark"] as const)(
    "SV-10: the %s tone draws Strova's open ring and the candidate's dot in the gap",
    (tone) => {
      const { container } = render(<BrandMark tone={tone} />);
      const svg = screen.getByRole("img", { name: "Strong Hire" });
      const parts = [...svg.querySelectorAll("[data-part]")].map((el) => el.getAttribute("data-part"));
      expect(parts).toEqual(["ring", "dot"]);
      const ring = container.querySelector('[data-part="ring"]');
      expect(ring).toHaveAttribute("d", ORBIT_RING);
      expect(ring).toHaveAttribute("stroke", "var(--brand-ring)");
      expect(ring).toHaveAttribute("fill", "none");
      expect(container.querySelector('[data-part="dot"]')).toHaveAttribute("fill", "var(--brand-dot)");
    },
  );

  it("SV-10: the ring stays open and the dot sits in its gap, clear of the stroke", () => {
    // The ring's two ends and the dot centre are on the same circle (r 18 around 24,24).
    const ends = [...ORBIT_RING.matchAll(/(-?\d+\.?\d*) (-?\d+\.?\d*)(?= A| *$)/g)].map((m) => [
      Number(m[1]),
      Number(m[2]),
    ]);
    expect(ends).toHaveLength(2);
    const onCircle = ([x, y]: number[]) => Math.hypot(x - 24, y - 24);
    for (const end of ends) expect(onCircle(end)).toBeCloseTo(18, 1);
    expect(onCircle([ORBIT_DOT.cx, ORBIT_DOT.cy])).toBeCloseTo(18, 1);
    // Each end (round cap, half the 5 px stroke) keeps at least 1.5 px from the dot.
    for (const [x, y] of ends) {
      expect(Math.hypot(x - ORBIT_DOT.cx, y - ORBIT_DOT.cy) - ORBIT_DOT.r - 2.5).toBeGreaterThanOrEqual(1.5);
    }
  });

  it("SV-10: never colors the dot like the ring", () => {
    const { container } = render(<BrandMark />);
    expect(container.querySelector('[data-part="dot"]')?.getAttribute("fill")).not.toBe(
      container.querySelector('[data-part="ring"]')?.getAttribute("stroke"),
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
