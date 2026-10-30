// SV-7, SV-8: Strova on the marketing site. Run with `pnpm test`.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { ANALYSING_64, COACHING_104, COACHING_64, INTERVIEWING_64 } from "../src/data/strova.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("SV-7: the header keeps the Strong Hire logo and name, with 'with Strova' muted", () => {
  const base = read("../src/layouts/Base.astro");
  assert.match(base, /<a class="brand" href="\/"><BrandMark \/>Strong Hire<span class="brand__with">with Strova<\/span><\/a>/);
  const css = read("../src/styles/site.css");
  assert.match(css, /\.brand__with \{[^}]*color: var\(--muted\)/);
});

test("SV-8: Meet Strova sits below the hero with the copy and the call to action", () => {
  const page = read("../src/pages/index.astro");
  const hero = page.indexOf('class="home-hero"');
  const meet = page.indexOf('id="strova"');
  assert.ok(hero >= 0 && meet > hero, "the section follows the hero");
  assert.ok(page.includes("Meet Strova, your interview partner."));
  assert.ok(
    page.includes(
      "Strova reads your resume, helps you build the stories you'll tell, and rehearses the real interview with you.",
    ),
  );
  // The call to action signs up; while the site is in waitlist mode it joins the waitlist, as the hero does.
  assert.match(page, /CTA === "signup" \? \(\s*<a class="btn" href=\{signupUrl\("strova"\)\}>Start with your resume<\/a>/);
  assert.match(page, /<Strova mode="coaching" size=\{104\} \/>/);
});

test("SV-8: the avatar is an inline SVG with its accessible label, and each copy has its own ids", () => {
  assert.match(COACHING_104, /^<svg role="img" aria-label="Strova is coaching" width="104" height="104"/);
  assert.match(ANALYSING_64, /aria-label="Strova is analysing"/);
  assert.match(INTERVIEWING_64, /aria-label="Strova is interviewing"/);
  const ids = [COACHING_104, COACHING_64, ANALYSING_64, INTERVIEWING_64].flatMap((s) =>
    [...s.matchAll(/id="([^"]+)"/g)].map((m) => m[1]),
  );
  assert.equal(new Set(ids).size, ids.length);
});

test("SV-8: the animation stops under reduced motion", () => {
  const css = read("../src/styles/strova.css");
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\s*\.strova \* \{ animation: none !important; \}/);
});
