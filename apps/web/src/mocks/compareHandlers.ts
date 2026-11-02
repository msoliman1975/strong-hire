/**
 * MSW for the resume comparison (RC-1 to RC-8). Ready at once: the newest non-main resume fits
 * best, so Use this one has something to switch. Its first gap is covered by the main resume (a
 * skill, Add to resume works); its second gap no resume covers (Craft a story).
 */
import { http, HttpResponse } from "msw";

import type { ComparedResume, ResumeComparisonOut } from "../api/types";
import type { MockStore } from "./db";

const API = "*/api";
const comparisons = new Map<string, ResumeComparisonOut>();

function newId() {
  return globalThis.crypto.randomUUID();
}

function build(store: MockStore, jobId: string, roleResumeId: string | null): ResumeComparisonOut | null {
  const live = store.db.resumes.filter((r) => !r.deleted && r.status === "extracted");
  if (live.length < 2) return null;
  const main = live.find((r) => r.is_main) ?? live[0];
  const best = [...live].reverse().find((r) => r.id !== main.id) ?? live[1];
  const ordered = [best, ...live.filter((r) => r.id !== best.id)];
  const resumes: ComparedResume[] = ordered.map((r, i) => ({
    resume_id: r.id,
    resume_name: r.name,
    is_main: r.is_main,
    deleted: false,
    gap_analysis_id: newId(),
    status: "ready",
    error: null,
    reused: false,
    match_score: 82 - i * 18,
    must_haves_total: 5,
    must_haves_shown: 5 - i * 2 > 0 ? 5 - i * 2 : 0,
    must_haves_missing: i === 0 ? [] : ["Kafka", "Distributed systems"],
    high_gaps: i,
    rank: i + 1,
    stale: false,
  }));
  return {
    id: newId(),
    job_target_id: jobId,
    status: "ready",
    resumes,
    recommended_resume_id: best.id,
    reason: `${best.name} fits best: match 82, against ${ordered
      .slice(1)
      .map((r, i) => `${r.name} ${64 - i * 18}`)
      .join(", ")}. It shows 5 of 5 must-haves.`,
    focus_resume_id: best.id,
    gaps: [
      {
        key: "k-kafka",
        summary: "Kafka is not shown",
        severity: "medium",
        related_requirement: "Kafka",
        source: {
          resume_id: main.id,
          resume_name: main.name ?? "Resume",
          line: "Kafka",
          place: "skills",
          company: null,
          can_add: true,
          in_resume: false,
        },
        status: "open",
        listed_in: [],
      },
      {
        key: "k-payments",
        summary: "No payments experience",
        severity: "high",
        related_requirement: "Payments or financial systems",
        source: null,
        status: "open",
        listed_in: [],
      },
    ],
    role_resume_id: roleResumeId,
    chosen_resume_id: null,
    new_runs: resumes.length,
    out_of_date: false,
    out_of_date_reason: null,
    created_at: new Date().toISOString(),
  };
}

function byId(id: unknown) {
  return [...comparisons.values()].find((c) => c.id === id);
}

function setGap(c: ResumeComparisonOut, key: unknown, status: "added" | "dismissed") {
  const gaps = c.gaps.map((g) => (g.key === key ? { ...g, status } : g));
  const next = { ...c, gaps };
  comparisons.set(c.job_target_id, next);
  return next;
}

export function compareHandlers(store: MockStore) {
  return [
    http.post(`${API}/roles/:jobId/resume-comparison`, ({ params }) => {
      const jobId = String(params.jobId);
      const roleResume = store.db.resumes.find((r) => r.is_main && !r.deleted)?.id ?? null;
      const c = build(store, jobId, comparisons.get(jobId)?.role_resume_id ?? roleResume);
      if (!c) {
        return HttpResponse.json(
          { detail: { code: "too_few_resumes", message: "Add another resume to compare them." } },
          { status: 409 },
        );
      }
      comparisons.set(jobId, c);
      return HttpResponse.json(c, { status: 202 });
    }),
    http.get(`${API}/roles/:jobId/resume-comparison`, ({ params }) => {
      const c = comparisons.get(String(params.jobId));
      return c ? HttpResponse.json(c) : HttpResponse.json({ detail: "Comparison not found" }, { status: 404 });
    }),
    http.post(`${API}/resume-comparisons/:id/use`, async ({ params, request }) => {
      const c = byId(params.id);
      if (!c) return HttpResponse.json({ detail: "Comparison not found" }, { status: 404 });
      const { resume_id } = (await request.json()) as { resume_id: string };
      const next = { ...c, chosen_resume_id: resume_id, role_resume_id: resume_id, focus_resume_id: resume_id };
      comparisons.set(c.job_target_id, next);
      return HttpResponse.json(next);
    }),
    http.post(`${API}/resume-comparisons/:id/hints/:key/add`, ({ params }) => {
      const c = byId(params.id);
      return c ? HttpResponse.json(setGap(c, params.key, "added")) : HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }),
    http.post(`${API}/resume-comparisons/:id/hints/:key/dismiss`, ({ params }) => {
      const c = byId(params.id);
      return c
        ? HttpResponse.json(setGap(c, params.key, "dismissed"))
        : HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }),
  ];
}

/** Tests: change the saved comparison of a role, for example to shape its gaps. */
export function patchMockComparison(jobId: string, patch: (c: ResumeComparisonOut) => ResumeComparisonOut) {
  const c = comparisons.get(jobId);
  if (c) comparisons.set(jobId, patch(c));
}
