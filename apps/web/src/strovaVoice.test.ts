/**
 * SV-15: the UI copy speaks of Strova by name and in her voice (ux-spec section 4.6). Scans the app
 * code (no tests, mocks or generated API types) for user-facing text: string literals and JSX text,
 * with comments removed.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { expect, it } from "vitest";

const SRC = resolve(__dirname);

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

/** The app's user-facing text, one entry per string literal or JSX text run. */
function copy(): { file: string; text: string }[] {
  return files(SRC)
    .filter((f) => /\.(ts|tsx)$/.test(f))
    .filter((f) => !/\.test\.tsx?$/.test(f) && !f.includes(`${join(SRC, "mocks")}`) && !f.endsWith("schema.gen.ts"))
    .flatMap((f) => {
      const source = readFileSync(f, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
      const texts = [
        ...source.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g),
        ...source.matchAll(/>([^<>{}]*[A-Za-z][^<>{}]*)</g),
      ].map((m) => (m[1] ?? m[2] ?? m[3] ?? "").trim());
      return texts.filter(Boolean).map((text) => ({ file: relative(SRC, f), text }));
    });
}

it("SV-15: the interface calls her Strova, never \"the coach\" or \"your coach\"", () => {
  const offenders = copy().filter(({ text }) => /\b(the|your) coach\b/i.test(text));
  expect(offenders).toEqual([]);
});

it("SV-15: no empty praise in the copy (earned praise names what earned it)", () => {
  const offenders = copy().filter(({ text }) =>
    /\b(great job|amazing|awesome|well done|nailed it|you got this|keep it up)\b|^great[.!]/i.test(text),
  );
  expect(offenders).toEqual([]);
});
