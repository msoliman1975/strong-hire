/**
 * Mocks must match the packages/core contracts: every mock payload is validated against the
 * JSON Schemas that strong_core exports into /schemas (CI checks those are fresh).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";

import { debriefApi, jobsApi, resumesApi, sessionsApi, gapApi } from "../api/planned";
import { authApi } from "../api/auth";
import { gapAnalysis, jobPosting, resume, scorecardFor, sessionPlan } from "./fixtures";

const SCHEMAS_DIR = resolve(__dirname, "../../../../schemas");

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);

const compiled = new Map<string, ReturnType<typeof ajv.compile>>();

/** Schemas carry an $id, so each one is compiled once and reused. */
function validator(name: string) {
  let validate = compiled.get(name);
  if (!validate) {
    const schema = JSON.parse(readFileSync(resolve(SCHEMAS_DIR, `${name}.schema.json`), "utf8")) as object;
    validate = ajv.compile(schema);
    compiled.set(name, validate);
  }
  return validate;
}

function expectValid(name: string, payload: unknown) {
  const validate = validator(name);
  const ok = validate(payload);
  expect(validate.errors ?? [], `${name} mock does not match its schema`).toEqual([]);
  expect(ok).toBe(true);
}

describe("mock payloads match the packages/core schemas", () => {
  it("JobPosting (IN-2)", () => expectValid("job_posting", jobPosting));
  it("Resume (IN-3)", () => expectValid("resume", resume));
  it("GapAnalysis (GA-1 to GA-3)", () => expectValid("gap_analysis", gapAnalysis));
  it("Scorecard for every interview type (FB-1, FB-2)", () => {
    for (const type of ["behavioral", "hiring_manager", "technical_qa", "case"] as const) {
      expectValid("scorecard", scorecardFor(type));
    }
  });

  it("an invalid payload fails, so the check is real", () => {
    const validate = validator("scorecard");
    expect(validate({ ...scorecardFor("behavioral"), hire_signal: "Maybe" })).toBe(false);
  });

  it("payloads the mock API builds at run time: SessionConfig, PlannedSession, ProgressSnapshot", async () => {
    await authApi.devLogin("schema@example.com");
    await authApi.signup({ age_confirmed: true, terms_accepted: true, training_consent: false });
    const job = await jobsApi.create({ raw_text: "x".repeat(200) });
    const resumeRecord = await resumesApi.upload(formWithText("Python engineer"));
    await jobsApi.setResume(job.id, resumeRecord.id);
    await gapApi.start(job.id);
    const session = await sessionsApi.create({
      job_target_id: job.id,
      config: { interview_type: "behavioral", difficulty: "realistic", mode: "realistic", duration_min: 30, level: "senior" },
    });
    await sessionsApi.end(session.id);
    expectValid("session_config", session.config);

    const debrief = await debriefApi.get(session.id);
    expectValid("scorecard", debrief.scorecard);

    const progress = await debriefApi.progress(job.id);
    expect(progress.snapshots.length).toBeGreaterThan(0);
    for (const snapshot of progress.snapshots) expectValid("progress_snapshot", snapshot);
    expect(sessionPlan.length).toBeGreaterThan(0);
  });
});

function formWithText(text: string): FormData {
  const form = new FormData();
  form.append("text", text);
  return form;
}
