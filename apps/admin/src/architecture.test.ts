/**
 * Mocks never reach production code: only main.tsx (behind import.meta.env.DEV) and tests may
 * import from src/mocks.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { expect, it } from "vitest";

const SRC = resolve(__dirname);
const MOCKS = join(SRC, "mocks");
const IMPORTS_MOCKS = /from\s+["'](\.\.?\/)+mocks\//;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

it("app code does not import the mocks", () => {
  const offenders = files(SRC)
    .filter((f) => /\.(ts|tsx)$/.test(f))
    .filter((f) => !/\.test\.tsx?$/.test(f) && !f.startsWith(MOCKS))
    .filter((f) => !f.endsWith("main.tsx") && !f.endsWith("test-setup.ts"))
    .filter((f) => IMPORTS_MOCKS.test(readFileSync(f, "utf8")))
    .map((f) => relative(SRC, f));
  expect(offenders).toEqual([]);
});
