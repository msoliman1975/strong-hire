/** SV-13: earned results carry a seal in the brand's ring shape; the word beside it carries the meaning. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CheckBadge } from "../BrandMark";
import { StoryStatusBadge } from "../../pages/stories/StoriesPage";
import { ProvenSeal, SEAL_PATH, SEAL_TEETH, VerdictSeal } from "./Seal";

describe("seals", () => {
  it("SV-13: the verdict seal is a closed ring with a check, and decorative", () => {
    const { container } = render(<VerdictSeal />);
    const svg = container.querySelector('svg[data-seal="verdict"]')!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg.querySelectorAll("circle")).toHaveLength(2);
    expect(svg.querySelector("path")).toHaveAttribute("d", "M15.5 24.5 L21.5 30.5 L33 18");
  });

  it("SV-13: the Proven seal is Strova's thinking zigzag, filled, with a white check", () => {
    const { container } = render(<ProvenSeal />);
    const svg = container.querySelector('svg[data-seal="proven"]')!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg.querySelector("path.sx-seal__fill")).toHaveAttribute("d", SEAL_PATH);
    const radii = [...SEAL_PATH.matchAll(/[ML](-?[\d.]+) (-?[\d.]+)/g)].map((m) => Math.hypot(Number(m[1]) - 24, Number(m[2]) - 24));
    expect(radii).toHaveLength(SEAL_TEETH * 2 + 1);
    radii.forEach((r, i) => expect(r).toBeCloseTo(i % 2 ? 19 : 22.5, 1));
  });

  it("SV-13: CheckBadge, used beside Hire and Strong Hire, draws the verdict seal", () => {
    const { container } = render(<CheckBadge />);
    expect(container.querySelector('svg[data-seal="verdict"]')).not.toBeNull();
  });

  it("SV-13: a Proven story's badge shows the Proven seal; Ready and Draft do not", () => {
    const { container, rerender } = render(<StoryStatusBadge status="proven" />);
    expect(screen.getByText("Proven")).toBeInTheDocument();
    expect(container.querySelector('svg[data-seal="proven"]')).not.toBeNull();
    rerender(<StoryStatusBadge status="ready" />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(container.querySelector('svg[data-seal="proven"]')).toBeNull();
  });
});
