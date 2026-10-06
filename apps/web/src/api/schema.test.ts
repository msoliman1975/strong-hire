/** src/api/schema.gen.ts must be the output of `pnpm gen:api` on the current openapi.json. */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, it } from "vitest";

const WEB = resolve(__dirname, "../..");

it("the generated API types are fresh", () => {
  const out = join(mkdtempSync(join(tmpdir(), "sh-openapi-")), "schema.gen.ts");
  const cli = resolve(WEB, "node_modules/openapi-typescript/bin/cli.js");
  execFileSync(process.execPath, [cli, resolve(WEB, "openapi.json"), "-o", out], { stdio: "pipe" });
  const fresh = readFileSync(out, "utf8");
  const committed = readFileSync(resolve(WEB, "src/api/schema.gen.ts"), "utf8");
  expect(committed, "Run `pnpm gen:api` and commit src/api/schema.gen.ts").toBe(fresh);
}, 30_000);
