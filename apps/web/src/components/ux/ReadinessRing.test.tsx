/** SV-11: readiness is drawn as Strova's ring, teal below the goal and green at or above it. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReadinessRing, readinessText } from "./ReadinessRing";

const meter = () => screen.getByRole("meter", { name: "Behavioral readiness" });

describe("ReadinessRing", () => {
  it("SV-11: before the first Realistic take it is an empty track with the goal tick and a dash", () => {
    const { container } = render(<ReadinessRing score={null} goal={75} label="Behavioral readiness" />);
    expect(meter()).toHaveAttribute("data-state", "empty");
    expect(meter()).toHaveAttribute("aria-valuenow", "0");
    expect(meter()).toHaveAttribute("aria-valuetext", "Not started, goal 75");
    expect(container.querySelector('[data-part="arc"]')).toBeNull();
    expect(container.querySelector('[data-part="goal"]')).not.toBeNull();
    expect(meter()).toHaveTextContent("–");
  });

  it("SV-11: below the goal the arc fills to the score and the goal tick stays", () => {
    const { container } = render(<ReadinessRing score={58} goal={75} label="Behavioral readiness" />);
    expect(meter()).toHaveAttribute("data-state", "below");
    expect(meter()).toHaveAttribute("aria-valuenow", "58");
    expect(meter()).toHaveAttribute("aria-valuetext", "58 of 100, goal 75");
    const arc = container.querySelector('[data-part="arc"]')!;
    const c = Number(arc.getAttribute("stroke-dasharray"));
    expect(Number(arc.getAttribute("stroke-dashoffset"))).toBeCloseTo(c * 0.42, 1);
    expect(container.querySelector('[data-part="goal"]')).not.toBeNull();
    expect(meter()).toHaveTextContent("58");
  });

  it("SV-11: at or above the goal the ring turns green, drops the tick and says so in text", () => {
    const { container } = render(<ReadinessRing score={75} goal={75} label="Behavioral readiness" />);
    expect(meter()).toHaveAttribute("data-state", "reached");
    expect(meter()).toHaveAttribute("aria-valuetext", "75 of 100, goal 75, goal reached");
    expect(container.querySelector('[data-part="goal"]')).toBeNull();
  });

  it("SV-11: small rings leave the number to the text beside them", () => {
    render(<ReadinessRing score={58} goal={75} size={24} label="Behavioral readiness" />);
    expect(meter()).not.toHaveTextContent("58");
    expect(readinessText(80, 75)).toBe("80 of 100, goal 75, goal reached");
  });
});
