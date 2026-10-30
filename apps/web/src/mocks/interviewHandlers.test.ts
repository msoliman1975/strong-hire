/** The U06 mocks behave like the API: suggestions (TG-3), interviews (RH-1), readiness (RH-2). */
import { afterEach, describe, expect, it } from "vitest";

import { API_BASE as BASE } from "../api/client";
import { jobTargetsApi, resumesApi } from "../api/inputs";
import { mockStore } from "./node";

async function json(path: string, init?: RequestInit) {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  return { status: resp.status, body: resp.status === 204 ? null : await resp.json() };
}

async function roleWithResume() {
  const form = new FormData();
  form.append("text", "Backend engineer, Python and Go.");
  const { resume } = await resumesApi.upload(form);
  await resumesApi.get(resume.id);
  const { job_target: job } = await jobTargetsApi.create({ text: "Senior engineer, payments. ".repeat(5) });
  return { job: await jobTargetsApi.get(job.id), resumeId: resume.id };
}

afterEach(() => {
  mockStore.db.interviews = [];
});

describe("interview mocks", () => {
  it("TG-3: suggestions list the standard loop as usual, with acting as", async () => {
    const { job } = await roleWithResume();
    const { body } = await json(`/roles/${job.id}/suggested-interviews`);
    expect(body.items.filter((i: { usual: boolean }) => i.usual).map((i: { interview_type: string }) => i.interview_type)).toEqual([
      "behavioral",
      "hiring_manager",
      "technical_qa",
    ]);
    expect(body.items[0].acting_as.text).toMatch(/^Strova is acting as /);
  });

  it("RH-1, RH-2: kept types become interviews; readiness has no score before a take; archive hides one", async () => {
    const { job, resumeId } = await roleWithResume();
    const created = await json(`/roles/${job.id}/interviews`, {
      method: "POST",
      body: JSON.stringify({ interview_types: ["behavioral", "technical_qa", "behavioral"] }),
    });
    expect(created.status).toBe(201);
    expect(created.body.map((i: { resume_id: string }) => i.resume_id)).toEqual([resumeId, resumeId]);
    const detail = await json(`/interviews/${created.body[0].id}`);
    expect(detail.body.readiness).toMatchObject({ score: null, goal: 75, kind: "practice_estimate" });
    expect(detail.body.takes).toEqual([]);
    await json(`/interviews/${created.body[1].id}`, { method: "DELETE" });
    const roles = await json("/roles");
    const mine = roles.body.find((r: { role: { id: string } }) => r.role.id === job.id);
    expect(mine.interviews.map((i: { interview: { interview_type: string } }) => i.interview.interview_type)).toEqual(["behavioral"]);
    const rehearsals = await json("/rehearsals");
    expect(rehearsals.body.next_interview_id).toBe(created.body[0].id);
  });
});
