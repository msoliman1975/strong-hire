/** Strova, the approved avatar (SV-1 to SV-5). */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Strova, STROVA_COLORS, STROVA_LABELS, STROVA_MODES, type StrovaMode } from ".";
import { ZIGZAG_PATH } from "./Strova";

const CSS = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "strova.css"), "utf-8");

function draw(mode: StrovaMode, size = 160, hat?: "coach" | "interviewer") {
  const { container } = render(<Strova mode={mode} size={size} hat={hat} />);
  const svg = container.querySelector("svg");
  if (!svg) throw new Error("no svg");
  return svg;
}

/** The effect element that identifies each mode (ux-spec section 4.2). */
const EFFECT_PART: Record<StrovaMode, string> = {
  listening: "path.sv-wave",
  speaking: "path.sv-wave.sv-d3",
  interviewing: "path.sv-check",
  thinking: "circle.sv-dot.sv-d3",
  analysing: "g.sv-scan",
  coaching: "g.sv-bob path.sv-twinkle",
  celebrating: "circle.sv-float",
};

describe("Strova", () => {
  it("SV-1: renders the seven modes with their mouth and effect", () => {
    expect(STROVA_MODES).toHaveLength(7);
    for (const mode of STROVA_MODES) {
      const svg = draw(mode);
      expect(svg.getAttribute("viewBox")).toBe("0 0 200 200");
      expect(svg.querySelector(EFFECT_PART[mode]), mode).not.toBeNull();
      const mouth = svg.querySelector('[data-part="mouth"]');
      if (mode === "speaking") {
        expect(mouth?.tagName.toLowerCase()).toBe("ellipse");
        expect(mouth).toHaveClass("sv-talk");
      } else {
        expect(mouth?.tagName.toLowerCase(), mode).toBe("path");
      }
      // The hair and face use the mockup's head transform.
      expect(svg.querySelectorAll('[transform="translate(40 29.6) scale(1.2)"]')).toHaveLength(3);
    }
  });

  it("SV-1: mouths and eyes follow the drawing", () => {
    expect(draw("coaching").querySelector('[data-part="mouth"]')).toHaveAttribute("d", "M91 114 Q100 120 109 114");
    expect(draw("analysing").querySelector('[data-part="mouth"]')).toHaveAttribute("d", "M91 116 L109 116");
    const thinkingEyes = [...draw("thinking").querySelectorAll("ellipse.sv-blink")];
    expect(thinkingEyes.map((e) => [e.getAttribute("cx"), e.getAttribute("cy")])).toEqual([
      ["88", "92"],
      ["116", "92"],
    ]);
  });

  it("SV-1: clip-path ids are unique per instance", () => {
    const { container } = render(
      <>
        <Strova mode="coaching" size={72} />
        <Strova mode="coaching" size={72} />
      </>,
    );
    const ids = [...container.querySelectorAll("clipPath")].map((c) => c.id);
    expect(new Set(ids).size).toBe(2);
    for (const id of ids) expect(container.querySelector(`[clip-path="url(#${id})"]`)).not.toBeNull();
  });

  it("SV-2: the ring colour shows the hat", () => {
    const ring = (svg: SVGSVGElement) => svg.querySelector('[data-part="ring"]');
    for (const mode of ["listening", "speaking", "interviewing"] as const) {
      expect(ring(draw(mode))).toHaveAttribute("stroke", STROVA_COLORS.interviewer.accent);
    }
    for (const mode of ["analysing", "coaching"] as const) {
      expect(ring(draw(mode))).toHaveAttribute("stroke", STROVA_COLORS.coach.accent);
    }
    expect(ring(draw("celebrating"))).toHaveAttribute("stroke", STROVA_COLORS.celebrating.accent);
    expect(ring(draw("thinking"))).toHaveAttribute("stroke", "#5332e6");
    expect(ring(draw("thinking", 160, "interviewer"))).toHaveAttribute("stroke", "#0b6e8c");
    expect(draw("thinking", 160, "interviewer").querySelector("circle")).toHaveAttribute("fill", "#e0f2f7");
  });

  it("SV-2: thinking and analysing get the zigzag ring; the others a plain ring", () => {
    for (const mode of STROVA_MODES) {
      const ring = draw(mode).querySelector('[data-part="ring"]');
      if (mode === "thinking" || mode === "analysing") {
        expect(ring?.tagName.toLowerCase()).toBe("path");
        expect(ring).toHaveAttribute("d", ZIGZAG_PATH);
        expect(ring).toHaveClass("sv-spin");
      } else {
        expect(ring?.tagName.toLowerCase(), mode).toBe("circle");
        expect(ring?.classList.contains("sv-pulse-ring"), mode).toBe(mode === "speaking" || mode === "celebrating");
      }
    }
    expect(ZIGZAG_PATH.startsWith("M196.0 100.0 L")).toBe(true);
    expect(ZIGZAG_PATH.match(/[ML]/g)).toHaveLength(57);
  });

  it("SV-3: the timings match the spec and every animation stops under reduced motion", () => {
    for (const rule of [
      "animation: sv-spin 9s linear infinite",
      "animation: sv-ring 1.6s ease-in-out infinite",
      "animation: sv-blink 4.5s infinite",
      "animation: sv-dot 1.4s ease-in-out infinite",
      "animation: sv-scan 2.4s ease-in-out infinite",
      "animation: sv-bob 2.6s ease-in-out infinite",
      "animation: sv-twinkle 1.8s ease-in-out infinite",
      "animation: sv-check 2.4s ease-in-out infinite",
      "animation: sv-wave 1.2s ease-in-out infinite",
      "animation: sv-talk 0.35s ease-in-out infinite alternate",
      "animation: sv-float 2.2s ease-in-out infinite",
    ]) {
      expect(CSS).toContain(rule);
    }
    const reduced = CSS.slice(CSS.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toContain("animation: none !important");
    expect(reduced).toContain(".sv-check { stroke-dashoffset: 0; }");
  });

  it("SV-4: every avatar is an image named for its state", () => {
    for (const mode of STROVA_MODES) {
      const { unmount } = render(<Strova mode={mode} size={40} />);
      expect(screen.getByRole("img", { name: STROVA_LABELS[mode] })).toBeInTheDocument();
      unmount();
    }
    expect(STROVA_LABELS.thinking).toBe("Strova is thinking");
  });

  it("SV-5: below 64 px the side effects are hidden", () => {
    for (const mode of STROVA_MODES) {
      expect(draw(mode, 40).querySelector('[data-part="effects"]'), mode).toBeNull();
      expect(draw(mode, 72).querySelector('[data-part="effects"]'), mode).not.toBeNull();
    }
    expect(draw("coaching", 63).querySelector('[data-part="effects"]')).toBeNull();
    expect(draw("coaching", 64).querySelector('[data-part="effects"]')).not.toBeNull();
  });
});
