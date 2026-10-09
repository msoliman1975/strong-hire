/**
 * Mocks must match the packages/core contracts: every mock payload is validated against the
 * JSON Schemas that strong_core exports into /schemas (CI checks those are fresh).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";

import { accountApi } from "../api/account";
import { authApi } from "../api/auth";
import { billingApi } from "../api/billing";
import { gapApi } from "../api/gap";
import { jobTargetsApi, resumesApi } from "../api/inputs";
import { sessionsApi } from "../api/sessions";
import { debriefApi } from "../api/scoring";
import { gapAnalysis, jobPosting, resume, scorecardFor, sessionPlan } from "./fixtures";

const SCHEMAS_DIR = resolve(__dirname, "../../../../schemas");
const OPENAPI = JSON.parse(readFileSync(resolve(__dirname, "../../openapi.json"), "utf8")) as object;

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
ajv.addSchema(OPENAPI, "openapi.json");

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

/** Validates a payload against a response schema of the real API (components in openapi.json). */
function expectApiShape(component: string, payload: unknown) {
  const validate = ajv.compile({ $ref: `openapi.json#/components/schemas/${component}` });
  const ok = validate(payload);
  expect(validate.errors ?? [], `${component} mock does not match openapi.json`).toEqual([]);
  expect(ok).toBe(true);
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
      expectValid("scorecard", scorecardFor(type, true));
    }
  });

  it("an invalid payload fails, so the check is real", () => {
    const validate = validator("scorecard");
    expect(validate({ ...scorecardFor("behavioral"), hire_signal: "Maybe" })).toBe(false);
  });

  it("payloads the mock API builds at run time: SessionConfig, PlannedSession, ProgressSnapshot", async () => {
    await authApi.devLogin("schema@example.com");
    await authApi.signup({ age_confirmed: true, terms_accepted: true, training_consent: false });
    const { job_target: job } = await jobTargetsApi.create({ text: "x".repeat(200) });
    const { resume: resumeRecord } = await resumesApi.upload(formWithText("Python engineer"));
    await resumesApi.get(resumeRecord.id);
    await gapApi.start(job.id, { resume_id: resumeRecord.id });
    const session = await sessionsApi.create({
      job_target_id: job.id,
      config: { interview_type: "behavioral", difficulty: "realistic", mode: "realistic", duration_min: 30, level: "senior" },
      channel: "voice",
    });
    await sessionsApi.joinVoice(session.id);
    await sessionsApi.end(session.id);
    expectValid("session_config", session.config);

    const debrief = await debriefApi.get(session.id);
    expectValid("scorecard", debrief.scorecard);
    expectApiShape("Debrief", debrief);

    const progress = await debriefApi.progress(job.id);
    expect(progress.snapshots.length).toBeGreaterThan(0);
    for (const snapshot of progress.snapshots) expectValid("progress_snapshot", snapshot);
    expectApiShape("JobProgress", progress);
    expect(progress.trends.length).toBeGreaterThan(0);
    expect(sessionPlan.length).toBeGreaterThan(0);
  });
});

describe("mocks of the real P2 endpoints match openapi.json", () => {
  it("job targets: create (202), job status, get, update (IN-1, IN-2, IN-4)", async () => {
    const accepted = await jobTargetsApi.create({ url: "https://example-board.test/jobs/1" });
    expectApiShape("JobTargetAccepted", accepted);
    expect(accepted.job_target.status).toBe("pending");
    expect(accepted.job?.status).toBe("queued");

    const job = await jobTargetsApi.job(accepted.job_target.id, accepted.job?.id ?? "");
    expectApiShape("JobOut", job);
    expect(job.result?.outcome).toBe("extracted");

    const target = await jobTargetsApi.get(accepted.job_target.id);
    expectApiShape("JobTargetOut", target);
    expect(target.generic_mode).toBe(false);
    expectValid("job_posting", target.posting);

    const updated = await jobTargetsApi.update(target.id, {
      posting: { ...jobPosting, company_name: "Tiny Startup" },
      stage: "Phone screen",
      context: { concerns: "System design" },
    });
    expectApiShape("JobTargetAccepted", updated);
    expect(updated.job_target.generic_mode).toBe(true);
    expect(updated.job_target.context.concerns).toBe("System design");
  });

  it("IN-1: LinkedIn needs pasted text, like the API (422 paste_required)", async () => {
    await expect(jobTargetsApi.create({ url: "https://www.linkedin.com/jobs/view/1" })).rejects.toMatchObject({
      status: 422,
      code: "paste_required",
    });
  });

  it("resumes: upload (202), job status, get, update (IN-3)", async () => {
    const accepted = await resumesApi.upload(formWithText("Python engineer"));
    expectApiShape("ResumeAccepted", accepted);
    const job = await resumesApi.job(accepted.resume.id, accepted.job?.id ?? "");
    expectApiShape("JobOut", job);
    const record = await resumesApi.get(accepted.resume.id);
    expectApiShape("ResumeOut", record);
    expect(record.status).toBe("extracted");
    expectApiShape("ResumeOut", await resumesApi.update(record.id, resume));
  });
});

describe("mocks of the real P6 endpoints match openapi.json", () => {
  it("gap analysis: start (202), get, run again (GA-1 to GA-3)", async () => {
    const { job_target: job } = await jobTargetsApi.create({ text: "y".repeat(200) });
    const { resume: record } = await resumesApi.upload(formWithText("Go engineer"));
    await jobTargetsApi.get(job.id);
    await resumesApi.get(record.id);

    await expect(gapApi.get(job.id)).rejects.toMatchObject({ status: 404 });
    await expect(gapApi.start(job.id)).rejects.toMatchObject({ status: 422 });

    const started = await gapApi.start(job.id, { resume_id: record.id });
    expectApiShape("GapAnalysisOut", started);
    const ready = await gapApi.get(job.id);
    expectApiShape("GapAnalysisOut", ready);
    expect(ready.status).toBe("ready");
    expectValid("gap_analysis", ready.analysis);

    const again = await gapApi.start(job.id);
    expect(again.resume_id).toBe(record.id);
    expect(again.id).not.toBe(started.id);
  });

  it("lists: job targets with dashboard numbers, and resumes", async () => {
    await jobTargetsApi.create({ text: "z".repeat(200) });
    await resumesApi.upload(formWithText("Data engineer"));
    const jobs = await jobTargetsApi.list();
    expect(jobs.length).toBeGreaterThan(0);
    for (const row of jobs) expectApiShape("JobTargetSummary", row);
    const resumes = await resumesApi.list();
    expect(resumes.length).toBeGreaterThan(0);
    for (const row of resumes) expectApiShape("ResumeOut", row);
  });
});

describe("mocks of the real P9 endpoints match openapi.json", () => {
  it("billing: plan, usage, checkout, portal, exit survey (BL-1, BL-2)", async () => {
    await authApi.devLogin("billing@example.com");
    await authApi.signup({ age_confirmed: true, terms_accepted: true, training_consent: false });
    expectApiShape("PlanOut", await billingApi.plan());
    const free = await billingApi.usage();
    expectApiShape("UsageOut", free);
    expect(free.plan).toBe("free");
    await expect(billingApi.portal("manage")).rejects.toMatchObject({ status: 404 });

    expectApiShape("RedirectOut", await billingApi.checkout());
    const paid = await billingApi.usage();
    expectApiShape("UsageOut", paid);
    expect(paid.plan).toBe("paid");
    await expect(billingApi.checkout()).rejects.toMatchObject({ status: 409, code: "already_subscribed" });

    expectApiShape("ExitSurveyOut", await billingApi.exitSurvey({ reason: "got_the_job", got_job: "yes" }));
    expectApiShape("RedirectOut", await billingApi.portal("cancel"));
    expect((await billingApi.usage()).cancel_at_period_end).toBe(true);
  });

  it("account: consent, export, delete (AC-1, AC-2)", async () => {
    await authApi.devLogin("account@example.com");
    await authApi.signup({ age_confirmed: true, terms_accepted: true, training_consent: false });
    expectApiShape("ConsentOut", await accountApi.setConsent(true));
    const started = await accountApi.startExport();
    expectApiShape("ExportOut", started);
    const ready = await accountApi.getExport(started.id);
    expectApiShape("ExportOut", ready);
    expect(ready.status).toBe("ready");
    expectApiShape("AccountDeletedOut", await accountApi.deleteAccount());
  });
});

function formWithText(text: string): FormData {
  const form = new FormData();
  form.append("text", text);
  return form;
}
