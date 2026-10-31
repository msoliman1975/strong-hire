/**
 * UI-1: a button that is a link keeps readable text on hover. The global `a:hover` colour is for
 * text links; each `.sx-btn` hover rule sets its own text colour so it wins over it.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "ux.css"), "utf-8");

describe("UI-1: ux.css hover colours", () => {
  it.each([".sx-btn:hover", ".sx-btn.ghost:hover", ".sx-btn.quiet:hover", ".sx-btn.dark:hover", ".sx-hero .sx-btn.ghost:hover"])(
    "%s sets a text colour",
    (selector) => {
      const rule = css.split("\n").find((line) => line.startsWith(`${selector} {`));
      expect(rule, selector).toMatch(/[^-]color:/);
    },
  );

  it("a card that is a link keeps its colours on hover", () => {
    expect(css).toMatch(/a\.sx-card, a\.sx-card:hover \{ color: inherit;/);
  });
});
