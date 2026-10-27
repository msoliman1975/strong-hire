/**
 * Mocks of the Custom interview endpoints (CU-2, CU-5, CU-8), with the same paths, status codes
 * and bodies as openapi.json, and the Custom parts of the debrief (CU-6). The check is a few
 * keyword rules so a click-through and the tests can see a refusal; the real check is a model
 * call in strong_api.custom.check.
 */
import { http, HttpResponse } from "msw/http";

import type { CreateSessionRequest } from "../api/sessions";
import type {
  Competency,
  CustomRecommendation,
  CustomSessionSpec,
  DebriefQuestion,
  FocusSuggestions,
  QuestionCheckOut,
  QuestionCheckRequest,
  QuestionRefusal,
  SavedQuestion,
  SavedQuestionIn,
  SavedQuestionPatch,
  Scorecard,
  StandardType,
} from "../api/types";
import { newId, type MockStore } from "./db";
import { gapAnalysis, jobPosting, scorecardFor } from "./fixtures";

const API = "*/api";

/** COMPETENCIES_BY_TYPE in strong_core.schemas.enums, for the mock tags. */
export const MOCK_COMPETENCIES: Record<StandardType, Competency[]> = {
  behavioral: ["ownership", "impact", "collaboration", "conflict_handling", "learning_from_failure", "communication"],
  hiring_manager: ["role_fit", "depth_of_experience", "judgment", "motivation", "team_fit", "scope_at_level"],
  technical_qa: ["technical_depth", "accuracy", "reasoning", "trade_offs", "clarity_of_explanation"],
  case: ["problem_framing", "structure", "user_and_business_sense", "estimation_logic", "prioritization", "recommendation"],
};

/** The fixed sentences of strong_api.custom.check. */
const REFUSALS: Record<QuestionRefusal, Record<"question" | "focus", string>> = {
  not_a_question: {
    question: "This does not look like an interview question.",
    focus: "This does not look like an interview topic.",
  },
  inappropriate: {
    question: "This question can't be used in a practice interview.",
    focus: "This topic can't be used in a practice interview.",
  },
  instructions: {
    question: "Questions can't give instructions to the interviewer.",
    focus: "Focus topics can't give instructions to the interviewer.",
  },
};

const INSTRUCTIONS = /\b(ignore|instructions?|system prompt|you are now|pretend|give me a (strong )?hire)\b/i;
const ABUSE = /\b(idiot|stupid|hate you)\b/i;
const QUESTION_START =
  /^(tell|describe|walk|explain|how|what|why|when|where|which|who|can|could|would|should|do|did|have|give|share|talk)\b/i;

function tagCategory(text: string): StandardType {
  const t = text.toLowerCase();
  if (/\b(estimate|how many|market size|metric|launch|product)\b/.test(t)) return "case";
  if (/\b(design|system|api|database|latency|scale|kubernetes|idempoten|cache|queue)\b/.test(t)) return "technical_qa";
  if (/\b(why (this|our)|motivat|team|manager|five years|career)\b/.test(t)) return "hiring_manager";
  return "behavioral";
}

const normalize = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, "").split(/\s+/).filter(Boolean).join(" ");

/** The near-duplicate flag: same words, or one contains the other. */
function duplicateIndex(text: string, existing: string[]): number | null {
  const mine = normalize(text);
  const i = existing.findIndex((e) => {
    const other = normalize(e);
    return other === mine || (other.length > 12 && mine.includes(other)) || (mine.length > 12 && other.includes(mine));
  });
  return i >= 0 ? i : null;
}

export function mockCheck(body: QuestionCheckRequest): QuestionCheckOut {
  const kind = body.kind ?? "question";
  const text = body.text.trim();
  const refuse = (refusal: QuestionRefusal, extra = ""): QuestionCheckOut => ({
    accepted: false,
    refusal,
    reason: `${REFUSALS[refusal][kind]}${extra ? ` ${extra}` : ""}`,
    category: null,
    competencies: [],
    duplicate_of: duplicateIndex(text, body.existing ?? []),
  });
  if (!text) return { ...refuse("not_a_question"), reason: kind === "question" ? "Type a question first." : "Type a topic first." };
  if (INSTRUCTIONS.test(text)) return refuse("instructions");
  if (ABUSE.test(text)) return refuse("inappropriate");
  if (kind === "question" && !text.endsWith("?") && !QUESTION_START.test(text)) {
    return refuse("not_a_question", "Write it the way an interviewer would ask it.");
  }
  const category = body.category ?? tagCategory(text);
  return {
    accepted: true,
    refusal: null,
    reason: "",
    category,
    competencies: MOCK_COMPETENCIES[category].slice(0, 2),
    duplicate_of: duplicateIndex(text, body.existing ?? []),
  };
}

/** The SessionConfig rules the API checks for a Custom session (strong_core.schemas). */
export function customProblem(config: CreateSessionRequest["config"]): string | null {
  const custom = config.custom;
  if (!custom) return "a custom session needs a custom setup";
  if (config.duration_min === 10) return "a custom session cannot be a mini interview";
  const cap = config.duration_min === 45 ? 8 : 5;
  if ((custom.questions ?? []).length > cap) return `a ${config.duration_min}-minute session takes at most ${cap} own questions`;
  const kinds = custom.categories.map((c) => c.category);
  if (kinds.length < 1 || kinds.length > 3) return "pick 1 to 3 categories";
  if (kinds.includes("case") && config.duration_min < 45) return "case needs a 45-minute session";
  if (kinds.includes("case") && kinds.length > 2) return "case allows at most one other category";
  const total = custom.categories.reduce((n, c) => n + c.share, 0);
  if (Math.abs(total - 1) > 0.01) return `category shares add up to ${total.toFixed(2)}, not 1`;
  if (kinds.length > 1) {
    for (const c of custom.categories) {
      if (c.share < 0.14) return `${c.category} needs a share of at least 0.15`;
      if (c.category === "case" && c.share < 0.49) return "case needs a share of at least 0.5";
    }
  }
  const stray = (custom.questions ?? []).filter((q) => !kinds.includes(q.category));
  if (stray.length) return "questions use categories not in the session";
  return null;
}

/** The 422 `question_refused` body of strong_api.custom.guard. */
export function refusedBody(result: QuestionCheckOut, where: Record<string, unknown> = {}) {
  return {
    detail: { code: "question_refused", message: result.reason, refusal: result.refusal, reason: result.reason, ...where },
  };
}

/**
 * CU-5 on the server (strong_api.custom.guard.check_custom_spec): every focus chip and own
 * question of a new Custom session is checked; the first refusal answers 422 with its index.
 */
export function customRefusal(
  custom: NonNullable<CreateSessionRequest["config"]["custom"]>,
): ReturnType<typeof refusedBody> | null {
  for (const c of custom.categories) {
    for (const [index, chip] of (c.focus ?? []).entries()) {
      const result = mockCheck({ text: chip, kind: "focus", category: c.category });
      if (!result.accepted) return refusedBody(result, { index, kind: "focus", category: c.category });
    }
  }
  for (const [index, q] of (custom.questions ?? []).entries()) {
    const result = mockCheck({ text: q.text, kind: "question", category: q.category });
    if (!result.accepted) return refusedBody(result, { index, kind: "question", category: q.category });
  }
  return null;
}

const ownRef = (i: number) => `own-${i + 1}`;

/** CU-6: a Custom scorecard: the planner's questions from the fixture, then the own questions. */
export function customScorecard(custom: CustomSessionSpec, generic = false): Scorecard {
  const base = scorecardFor("behavioral", generic);
  const own = custom.questions.map((q, i) => ({
    question_ref: ownRef(i),
    question_text: q.text,
    scores: q.competencies.map((competency) => ({
      competency,
      score: 3,
      justification: "Gave a specific example with a clear result.",
      quotes: ["I set up the plan and checked in every week."],
    })),
    value_scores: [],
    strengths: ["Specific example"],
    misses: ["Could have named the trade-off"],
    story_id: null,
    story_fix: null,
    delivery: null,
  }));
  return { ...base, per_question: [...base.per_question, ...own] };
}

/** CU-6: the plan's questions with their source and category, joined by question_ref. */
export function customDebriefQuestions(custom: CustomSessionSpec): DebriefQuestion[] {
  const base = scorecardFor("behavioral").per_question;
  const kinds = custom.categories.map((c) => c.category);
  const planner: DebriefQuestion[] = base.map((q, i) => ({
    question_ref: q.question_ref,
    text: q.question_text,
    source: "planner",
    category: kinds[i % kinds.length],
    competencies: MOCK_COMPETENCIES[kinds[i % kinds.length]].slice(0, 2),
    must_ask: false,
    verbatim: false,
  }));
  const own: DebriefQuestion[] = custom.questions.map((q, i) => ({
    question_ref: ownRef(i),
    text: q.text,
    source: "candidate",
    category: q.category,
    competencies: q.competencies,
    must_ask: q.must_ask,
    verbatim: q.verbatim,
  }));
  return [...own.filter((q) => q.must_ask), ...planner, ...own.filter((q) => !q.must_ask)];
}

/**
 * CU-10: the mock's Custom next session, behavioral and technical Q&A with chips from the session
 * plan. The real rule (gaps under the bar in two or more practiced types) is in
 * strong_api.scoring.progress; the mock offers it once a job has two completed Realistic sessions.
 */
export function mockCustomRecommendation(): CustomRecommendation {
  const topics = (type: StandardType, lead: string) => [
    lead,
    ...(gapAnalysis.session_plan.find((p) => p.interview_type === type)?.focus_topics ?? []).slice(0, 2),
  ];
  return {
    interview_type: "custom",
    difficulty: "realistic",
    duration_min: 30,
    custom: {
      categories: [
        { category: "technical_qa", share: 0.5, focus: topics("technical_qa", "Trade offs") },
        { category: "behavioral", share: 0.5, focus: topics("behavioral", "Conflict handling") },
      ],
      questions: [],
    },
    focus_topics: ["Trade offs", "Conflict handling"],
    reason:
      "Your scores under the bar of 3 span several kinds of interview: technical Q&A (trade offs 2.0), " +
      "behavioral (conflict handling 2.5). A Custom session practices them together.",
  };
}

/** CU-2: chips from the gap analysis and the posting, the first few preselected. */
export function mockFocus(jobId: string, gapId: string | null): FocusSuggestions {
  const focus = (suggested: string[], pre = 2) => ({ suggested: suggested.slice(0, 8), preselected: suggested.slice(0, pre) });
  const plan = (type: StandardType) => gapAnalysis.session_plan.find((p) => p.interview_type === type)?.focus_topics ?? [];
  return {
    job_target_id: jobId,
    gap_analysis_id: gapId,
    behavioral: focus([...plan("behavioral"), "Conflict with a peer"]),
    technical_qa: focus([...plan("technical_qa"), ...jobPosting.must_have_skills]),
    hiring_manager: focus([...plan("hiring_manager"), ...gapAnalysis.probe_areas]),
    case: focus(["Payments product sense", "Estimation"], 1),
  };
}

const SAVED_MAX = 50;

export function customHandlers(store: MockStore) {
  const db = () => store.db;
  const locked = () => db().siteStatus.custom_interview_access === "paid_only" && !db().usage.full_interviews_allowed;
  const conflict = (code: string, message: string) => HttpResponse.json({ detail: { code, message } }, { status: 409 });
  const invalid = (msg: string) => HttpResponse.json({ detail: [{ msg: `Value error, ${msg}` }] }, { status: 422 });
  /** Competencies that fit the category, else the check's tags (strong_api.custom.router). */
  const fitting = (category: StandardType, given: Competency[] | null | undefined, tags: Competency[]) =>
    given && given.length >= 1 && given.length <= 3 && given.every((c) => MOCK_COMPETENCIES[category].includes(c))
      ? given
      : tags;
  const duplicate = (text: string, skip?: string) =>
    db().savedQuestions.some((q) => q.id !== skip && normalize(q.text) === normalize(text));

  return [
    http.post(`${API}/custom/questions/check`, async ({ request }) => {
      if (locked()) {
        return HttpResponse.json(
          {
            detail: {
              code: "upgrade_required",
              message: "Custom interviews are part of the subscription. Subscribe to build your own interview.",
              upgrade_url: "/upgrade",
            },
          },
          { status: 403 },
        );
      }
      const body = (await request.json()) as QuestionCheckRequest;
      if (typeof body.text !== "string" || body.text.length > 2000) return invalid("text is too long");
      return HttpResponse.json(mockCheck(body));
    }),
    http.get(`${API}/custom/focus`, ({ request }) => {
      const jobId = new URL(request.url).searchParams.get("job_id") ?? "";
      const job = db().jobs.find((j) => j.id === jobId);
      if (!job) return HttpResponse.json({ detail: "Job target not found" }, { status: 404 });
      const gap = db().gaps[jobId];
      return HttpResponse.json(mockFocus(jobId, gap?.status === "ready" ? gap.id : null));
    }),
    http.get(`${API}/questions/mine`, () => HttpResponse.json(db().savedQuestions)),
    http.post(`${API}/questions/mine`, async ({ request }) => {
      const body = (await request.json()) as SavedQuestionIn;
      const text = body.text?.trim() ?? "";
      if (!text || text.length > 500) return invalid("text must be 1 to 500 characters");
      // CU-5: the server checks the text again before it stores it, and tags it.
      const check = mockCheck({ text, kind: "question", category: body.category });
      if (!check.accepted) return HttpResponse.json(refusedBody(check), { status: 422 });
      if (db().savedQuestions.length >= SAVED_MAX) {
        return conflict("saved_questions_full", `You can keep ${SAVED_MAX} questions. Delete one to add another.`);
      }
      if (duplicate(text)) return conflict("duplicate_question", "This question is already in your list.");
      const now = new Date().toISOString();
      const row: SavedQuestion = {
        id: newId(),
        text,
        category: body.category,
        competencies: fitting(body.category, body.competencies, check.competencies),
        bank_ref: body.bank_ref ?? null,
        created_at: now,
        updated_at: now,
      };
      db().savedQuestions.unshift(row);
      store.save();
      return HttpResponse.json(row, { status: 201 });
    }),
    http.patch(`${API}/questions/mine/:id`, async ({ params, request }) => {
      const row = db().savedQuestions.find((q) => q.id === params.id);
      if (!row) return HttpResponse.json({ detail: "Saved question not found" }, { status: 404 });
      const body = (await request.json()) as SavedQuestionPatch;
      const next = {
        text: body.text?.trim() ?? row.text,
        category: body.category ?? row.category,
        competencies: body.competencies ?? row.competencies,
      };
      if (!next.text || next.text.length > 500) return invalid("text must be 1 to 500 characters");
      // CU-5: a new text or category is checked again and, when the competencies do not fit, re-tagged.
      let tags = next.competencies;
      if (next.text !== row.text || next.category !== row.category) {
        const check = mockCheck({ text: next.text, kind: "question", category: next.category });
        if (!check.accepted) return HttpResponse.json(refusedBody(check), { status: 422 });
        tags = check.competencies;
      }
      next.competencies = fitting(next.category, next.competencies, tags);
      if (next.competencies.length === 0) return invalid(`competencies do not belong to ${next.category}`);
      if (body.text !== undefined && body.text !== null && duplicate(next.text, row.id)) {
        return conflict("duplicate_question", "This question is already in your list.");
      }
      Object.assign(row, next, { updated_at: new Date().toISOString() });
      store.save();
      return HttpResponse.json(row);
    }),
    http.delete(`${API}/questions/mine/:id`, ({ params }) => {
      const before = db().savedQuestions.length;
      db().savedQuestions = db().savedQuestions.filter((q) => q.id !== params.id);
      if (db().savedQuestions.length === before) {
        return HttpResponse.json({ detail: "Saved question not found" }, { status: 404 });
      }
      store.save();
      return new HttpResponse(null, { status: 204 });
    }),
  ];
}
