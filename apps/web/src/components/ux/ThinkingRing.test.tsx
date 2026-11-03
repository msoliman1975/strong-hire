/** SV-12: every loading state shows Strova's thinking ring beside its text. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Loading } from "../ui";
import { THINKING_PATH, THINKING_TEETH, ThinkingRing } from "./ThinkingRing";

describe("ThinkingRing", () => {
  it("SV-12: the zigzag alternates two radii, with deep enough teeth to read at 20 px", () => {
    const points = [...THINKING_PATH.matchAll(/[ML](-?[\d.]+) (-?[\d.]+)/g)].map((m) => Math.hypot(Number(m[1]) - 24, Number(m[2]) - 24));
    expect(points).toHaveLength(THINKING_TEETH * 2 + 1);
    points.forEach((r, i) => expect(r).toBeCloseTo(i % 2 ? 15 : 20, 1));
  });

  it("SV-12: it is decorative and wears the coach hat unless told otherwise", () => {
    const { container, rerender } = render(<ThinkingRing />);
    const svg = container.querySelector("svg.sx-thinking")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("data-hat", "coach");
    rerender(<ThinkingRing hat="interviewer" />);
    expect(container.querySelector("svg.sx-thinking")).toHaveAttribute("data-hat", "interviewer");
  });

  it("SV-12: Loading shows the thinking ring and keeps its text as the status", () => {
    render(<Loading label="Loading your stories" />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Loading your stories");
    expect(status.querySelector("svg.sx-thinking")).not.toBeNull();
  });
});
