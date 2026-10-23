/**
 * src/api/schema.gen.ts must be the output of `pnpm gen:api` on the current API document. The
 * admin app reads apps/web/openapi.json, which the API test suite keeps fresh.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, it } from "vitest";

const ADMIN = resolve(__dirname, "../..");
const OPENAPI = resolve(ADMIN, "../web/openapi.json");

it("the generated API types are fresh", () => {
  const out = join(mkdtempSync(join(tmpdir(), "sh-admin-openapi-")), "schema.gen.ts");
  const cli = resolve(ADMIN, "node_modules/openapi-typescript/bin/cli.js");
  execFileSync(process.execPath, [cli, OPENAPI, "-o", out], { stdio: "pipe" });
  const fresh = readFileSync(out, "utf8");
  const committed = readFileSync(resolve(ADMIN, "src/api/schema.gen.ts"), "utf8");
  expect(committed, "Run `pnpm gen:api` and commit src/api/schema.gen.ts").toBe(fresh);
}, 30_000);
