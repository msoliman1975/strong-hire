// Q13: guides are built only from reviewed, published profiles. Run with `pnpm test`.
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { GUIDES_PUBLISHED, loadGuides } from "../src/data/guides.ts";

const PROFILE = new URL("../../../profiles/google.json", import.meta.url);

test("no guide is published today", () => {
  assert.deepEqual(GUIDES_PUBLISHED, []);
  assert.deepEqual(loadGuides(), []);
});

test("a published slug without a reviewer builds nothing", () => {
  assert.deepEqual(loadGuides(["google"]), []);
});

test("a reviewed, published profile builds one guide per role family", () => {
  const profile = JSON.parse(readFileSync(PROFILE, "utf8"));
  profile.meta.reviewed_by = "reviewer@example.com";
  const dir = mkdtempSync(join(tmpdir(), "guides-"));
  writeFileSync(join(dir, "google.json"), JSON.stringify(profile));
  const guides = loadGuides(["google"], dir);
  assert.deepEqual(
    guides.map((g) => g.role),
    profile.loop_structure.map((l) => l.role_family),
  );
  assert.ok(guides[0].rounds.length > 0);
  assert.ok(guides[0].patterns.length > 0);
});
