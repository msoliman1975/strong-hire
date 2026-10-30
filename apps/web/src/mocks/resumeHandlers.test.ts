/** The U04 mocks behave like the API: main resume (RM-2), issues (RM-5), story ideas (RM-4), plan settings (PS-2). */
import { afterEach, describe, expect, it } from "vitest";

import { API_BASE as BASE } from "../api/client";
import { resumesApi } from "../api/inputs";
import { mockStore } from "./node";
import { missingParts } from "./resumeHandlers";


async function upload(text: string) {
  const form = new FormData();
  form.append("text", text);
  const { resume } = await resumesApi.upload(form);
  return resumesApi.get(resume.id);
}

afterEach(() => {
  mockStore.db.resumes = [];
});

describe("resume mocks", () => {
  it("RM-2: the first resume is main, switching moves it, deleting the main moves it to the newest", async () => {
    const a = await upload("Backend engineer, Python and Go.");
    const b = await upload("Second resume text, Python and Go.");
    expect(a.is_main).toBe(true);
    expect(b.is_main).toBe(false);
    await fetch(`${BASE}/resumes/${b.id}/main`, { method: "POST" });
    const listed = (await (await fetch(`${BASE}/resumes`)).json()) as { id: string; is_main: boolean }[];
    expect(listed.map((r) => [r.id, r.is_main])).toEqual([
      [b.id, true],
      [a.id, false],
    ]);
    await fetch(`${BASE}/resumes/${b.id}`, { method: "DELETE" });
    expect((await resumesApi.get(a.id)).is_main).toBe(true);
  });

  it("RM-4: story ideas list achievements with missing parts; Not a story hides one", async () => {
    const r = await upload("Backend engineer, Python and Go.");
    const ideas = await (await fetch(`${BASE}/resumes/${r.id}/story-ideas`)).json();
    expect(ideas.ideas.length).toBeGreaterThan(0);
    const first = ideas.ideas[0];
    expect(first.missing_parts).toEqual(missingParts(first.achievement));
    await fetch(`${BASE}/resumes/${r.id}/story-ideas/dismiss`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ resume_line_ref: first.resume_line_ref }),
    });
    const after = await (await fetch(`${BASE}/resumes/${r.id}/story-ideas`)).json();
    expect(after.ideas.map((i: { achievement: string }) => i.achievement)).not.toContain(first.achievement);
  });

  it("RM-5: the issues endpoint answers open and accepted lists", async () => {
    const r = await upload("Backend engineer, Python and Go.");
    const body = await (await fetch(`${BASE}/resumes/${r.id}/issues`)).json();
    expect(Array.isArray(body.open)).toBe(true);
    expect(body.accepted).toEqual([]);
  });

  it("RM-4: missing parts follow the API's rule", () => {
    expect(missingParts("Led the payout redesign")).toEqual(["stakes", "reflection"]);
    expect(missingParts("Payout service redesign")).toEqual(["action", "stakes", "reflection"]);
  });
});
