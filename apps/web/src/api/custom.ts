/**
 * Custom interviews (docs/custom-interview-spec.md): the CU-5 check of an own question or focus
 * chip, the suggested focus chips (CU-2), saved questions (CU-8) and "Run this setup again" (CU-9).
 *
 * Errors carry detail.code: 403 `upgrade_required` (CU-11), 429 `rate_limited`, 503
 * `check_unavailable`, 409 `duplicate_question` and `saved_questions_full`, and 422
 * `question_refused` when the server-side check (CU-5) refuses text that is stored or starts a
 * session (see `questionRefusal`).
 */
import { ApiError, apiClient, unwrap } from "./client";
import type {
  FocusSuggestions,
  QuestionCheckOut,
  QuestionCheckRequest,
  SavedQuestion,
  SavedQuestionIn,
  SavedQuestionPatch,
  SessionSetup,
} from "./types";

/** A 422 `question_refused`: the server's CU-5 check refused a question or focus chip. */
export interface QuestionRefused {
  reason: string;
  refusal: string | null;
  /** At session create: the index in `custom.questions`, or in the category's `focus` list. */
  index: number | null;
  kind: "question" | "focus" | null;
  category: string | null;
}

export function questionRefusal(err: unknown): QuestionRefused | null {
  if (!(err instanceof ApiError) || err.status !== 422 || err.code !== "question_refused") return null;
  const d = err.detail ?? {};
  return {
    reason: typeof d.reason === "string" && d.reason ? d.reason : err.message,
    refusal: typeof d.refusal === "string" ? d.refusal : null,
    index: typeof d.index === "number" ? d.index : null,
    kind: d.kind === "question" || d.kind === "focus" ? d.kind : null,
    category: typeof d.category === "string" ? d.category : null,
  };
}

export const customApi = {
  /** CU-5: refuse or tag one own question (kind "question") or free-text chip (kind "focus"). */
  check: async (body: QuestionCheckRequest) =>
    unwrap(await apiClient.POST("/custom/questions/check", { body })) as QuestionCheckOut,
  /** CU-2: suggested and preselected focus chips per category. */
  focus: async (jobId: string, resumeId?: string | null) =>
    unwrap(
      await apiClient.GET("/custom/focus", {
        params: { query: { job_id: jobId, resume_id: resumeId ?? undefined } },
      }),
    ) as FocusSuggestions,
  /** CU-9: an earlier session's setup, shaped like the POST /sessions body. Creates nothing. */
  repeat: async (sessionId: string) =>
    unwrap(
      await apiClient.POST("/sessions/{session_id}/repeat", {
        params: { path: { session_id: sessionId } },
      }),
    ) as SessionSetup,
};

export const savedQuestionsApi = {
  /** CU-8: newest first. */
  list: async () => unwrap(await apiClient.GET("/questions/mine")) as SavedQuestion[],
  create: async (body: SavedQuestionIn) =>
    unwrap(await apiClient.POST("/questions/mine", { body })) as SavedQuestion,
  update: async (id: string, body: SavedQuestionPatch) =>
    unwrap(
      await apiClient.PATCH("/questions/mine/{question_id}", {
        params: { path: { question_id: id } },
        body,
      }),
    ) as SavedQuestion,
  remove: async (id: string) => {
    unwrap(
      await apiClient.DELETE("/questions/mine/{question_id}", {
        params: { path: { question_id: id } },
      }),
    );
  },
};
