/**
 * MSW handlers for U08, with the paths and bodies of apps/api strong_api.suggestions: GET
 * /suggestions?place=..., accept, dismiss and undo. One sample of every kind, shaped like the
 * worker's fake fixtures; their status lives in memory. Accept here changes no story or resume:
 * the screens that show suggestions (U09 to U11) mock what they need.
 */
import { http, HttpResponse } from "msw/http";

import type { Suggestion, SuggestionAcceptIn, SuggestionAcceptOut, SuggestionKind } from "../api/types";

const API = "*/api";
const STORY = "11111111-1111-4111-8111-111111111111"; // the story library seed's first story
const AT = "2026-10-30T10:00:00Z";

type Place = "debrief" | "story" | "role" | "stories" | "resume";

const PLACE_KINDS: Record<Place, SuggestionKind[]> = {
  debrief: ["tune_story", "new_story", "missing_skill"],
  story: ["tune_story", "tailor_role", "review"],
  role: ["missing_skill", "tailor_role"],
  stories: ["tune_story", "missing_skill", "tailor_role", "story_idea"],
  resume: ["improve_resume_line", "story_idea"],
};

const BLANK = {
  status: "open",
  source_session_id: null,
  source_question_ref: null,
  source_resume_id: null,
  job_target_id: null,
  story_id: null,
  resume_id: null,
  prompt_ref: null,
  created_at: AT,
  resolved_at: null,
} as const;

const RESULT_AFTER = "We finished a week before Black Friday and not one payment failed.";
const RESULT_QUOTE = "we were done a week before Black Friday and not one payment failed";

/** One sample of every kind; ids are per kind, so a test can find each one. */
export function sampleSuggestions(ids: {
  sessionId?: string | null;
  jobId?: string | null;
  resumeId?: string | null;
} = {}): Suggestion[] {
  const { sessionId = null, jobId = null, resumeId = null } = ids;
  const base = { ...BLANK, source_session_id: sessionId, job_target_id: jobId };
  return [
    {
      ...base,
      id: "5a000000-0000-4000-8000-000000000001",
      kind: "tune_story",
      story_id: STORY,
      source_question_ref: "q1",
      prompt_ref: "coach/suggest_tune.v1",
      reason: "Your answer gave the result a number the story does not have.",
      payload: {
        kind: "tune_story",
        edit: { part: "result", before: "The migration went well.", after: RESULT_AFTER, quotes: [RESULT_QUOTE] },
      },
    },
    {
      ...base,
      id: "5a000000-0000-4000-8000-000000000002",
      kind: "new_story",
      source_question_ref: "q2",
      prompt_ref: "coach/suggest_new_story.v1",
      reason: "Your answer scored 4 of 4. It is not a story yet.",
      payload: {
        kind: "new_story",
        title: "Checkout migration before Black Friday",
        context: "We were moving checkout to a new payments provider.",
        stakes: "Black Friday was a month out and checkout could not break.",
        action: "I wrote the rollback plan and moved traffic in five percent steps.",
        result: RESULT_AFTER,
        reflection: null,
        skills: ["ownership", "impact"],
        quotes: [RESULT_QUOTE],
      },
    },
    {
      ...base,
      id: "5a000000-0000-4000-8000-000000000003",
      kind: "missing_skill",
      reason: "None of your stories shows conflict handling yet.",
      payload: { kind: "missing_skill", competency: "conflict_handling" },
    },
    {
      ...base,
      id: "5a000000-0000-4000-8000-000000000004",
      kind: "tailor_role",
      source_session_id: null,
      story_id: STORY,
      prompt_ref: "coach/suggest_tailor.v1",
      reason: "Checkout migration leads for ownership at Stripe.",
      payload: {
        kind: "tailor_role",
        company: "Stripe",
        competency: "ownership",
        note: "Lead with the rollback plan you wrote: Stripe probes for owning risk end to end.",
      },
    },
    {
      ...BLANK,
      id: "5a000000-0000-4000-8000-000000000005",
      kind: "improve_resume_line",
      story_id: STORY,
      resume_id: resumeId,
      prompt_ref: "coach/suggest_resume_line.v1",
      reason: "Your story “Checkout migration” has a result this line does not show.",
      payload: {
        kind: "improve_resume_line",
        resume_line_ref: "roles[0].achievements[1]",
        before: "Led checkout migration to new payments provider",
        after: "Led checkout migration to a new payments provider a week before Black Friday, with zero failed payments",
        quotes: [RESULT_QUOTE],
      },
    },
    {
      ...BLANK,
      id: "5a000000-0000-4000-8000-000000000006",
      kind: "story_idea",
      source_resume_id: resumeId,
      resume_id: resumeId,
      reason: "Built the refunds API is on your resume, and no story tells it yet.",
      payload: {
        kind: "story_idea",
        achievement: "Built the refunds API used by 40,000 merchants",
        role: "Software Engineer II, Shoply",
        resume_line_ref: "roles[0].achievements[0]",
        skills: ["impact", "technical_depth"],
        missing_parts: ["stakes", "reflection"],
      },
    },
    {
      ...BLANK,
      id: "5a000000-0000-4000-8000-000000000007",
      kind: "review",
      story_id: STORY,
      prompt_ref: "coach/review.v1",
      reason: "The action is clear and yours. The result needs the number you gave me.",
      payload: {
        kind: "review",
        review: {
          summary: "The action is clear and yours. The result needs the number you gave me.",
          notes: [
            {
              part: "result",
              note: "You said not one payment failed. Put that in the result.",
              edit: { part: "result", before: "The migration went well.", after: RESULT_AFTER, quotes: [RESULT_QUOTE] },
            },
            { part: "reflection", note: "Say what you would do differently next time.", edit: null },
          ],
        },
      },
    },
  ];
}

/** Status changes by suggestion id (accept, dismiss, undo). Tests reset it. */
const resolved = new Map<string, Pick<Suggestion, "status" | "resolved_at">>();

export function resetMockSuggestions(): void {
  resolved.clear();
}

function current(s: Suggestion): Suggestion {
  return { ...s, ...resolved.get(s.id) };
}

/** DB-4: the open suggestions of one take, for the mock debrief. */
export function debriefSuggestions(sessionId: string, jobId: string): Suggestion[] {
  return sampleSuggestions({ sessionId, jobId })
    .filter((s) => PLACE_KINDS.debrief.includes(s.kind))
    .map(current)
    .filter((s) => s.status === "open");
}

function find(id: string): Suggestion | undefined {
  const found = sampleSuggestions().find((s) => s.id === id);
  return found && current(found);
}

const notOpen = () =>
  HttpResponse.json(
    { detail: { code: "not_open", message: "This suggestion was already accepted or dismissed." } },
    { status: 409 },
  );

export function suggestionHandlers() {
  return [
    http.get(`${API}/suggestions`, ({ request }) => {
      const q = new URL(request.url).searchParams;
      const place = q.get("place") as Place | null;
      if (!place || !(place in PLACE_KINDS)) return HttpResponse.json({ detail: "place" }, { status: 422 });
      const items = sampleSuggestions({
        sessionId: q.get("session_id"),
        jobId: q.get("job_target_id"),
        resumeId: q.get("resume_id"),
      })
        .filter((s) => PLACE_KINDS[place].includes(s.kind))
        .map(current)
        .filter((s) => s.status === "open");
      return HttpResponse.json(items);
    }),
    http.post(`${API}/suggestions/:id/accept`, async ({ params, request }) => {
      const s = find(String(params.id));
      if (!s) return HttpResponse.json({ detail: "Suggestion not found" }, { status: 404 });
      if (s.status !== "open") return notOpen();
      const body = (await request.json().catch(() => ({}))) as SuggestionAcceptIn;
      resolved.set(s.id, { status: "accepted", resolved_at: new Date().toISOString() });
      const p = s.payload;
      const out: SuggestionAcceptOut = {
        suggestion: current(s),
        story_id: s.story_id ?? (p.kind === "new_story" ? "5b000000-0000-4000-8000-000000000001" : null),
        resume_id: s.resume_id,
        crafting:
          p.kind === "missing_skill"
            ? { competency: p.competency, job_target_id: s.job_target_id, achievement: null, skills: [] }
            : p.kind === "story_idea"
              ? { competency: null, job_target_id: null, achievement: p.achievement, skills: p.skills }
              : null,
        can_undo: ["tune_story", "tailor_role", "improve_resume_line", "review"].includes(s.kind) && !(
          s.kind === "review" && body.parts?.length === 0
        ),
      };
      return HttpResponse.json(out);
    }),
    http.post(`${API}/suggestions/:id/dismiss`, ({ params }) => {
      const s = find(String(params.id));
      if (!s) return HttpResponse.json({ detail: "Suggestion not found" }, { status: 404 });
      if (s.status !== "open") return notOpen();
      resolved.set(s.id, { status: "dismissed", resolved_at: new Date().toISOString() });
      return HttpResponse.json(current(s));
    }),
    http.post(`${API}/suggestions/:id/undo`, ({ params }) => {
      const s = find(String(params.id));
      if (!s) return HttpResponse.json({ detail: "Suggestion not found" }, { status: 404 });
      if (s.status !== "accepted")
        return HttpResponse.json({ detail: { code: "cannot_undo", message: "There is nothing to undo." } }, { status: 409 });
      resolved.delete(s.id);
      return HttpResponse.json({ ...s, status: "open", resolved_at: null });
    }),
  ];
}
