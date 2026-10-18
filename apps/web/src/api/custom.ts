/**
 * Custom interviews (docs/custom-interview-spec.md): the CU-5 check of an own question or focus
 * chip, the suggested focus chips (CU-2), saved questions (CU-8) and "Run this setup again" (CU-9).
 *
 * Errors carry detail.code: 403 `upgrade_required` (CU-11), 429 `rate_limited`, 503
 * `check_unavailable`, 409 `duplicate_question` and `saved_questions_full`.
 */
import { apiClient, unwrap } from "./client";
import type {
  FocusSuggestions,
  QuestionCheckOut,
  QuestionCheckRequest,
  SavedQuestion,
  SavedQuestionIn,
  SavedQuestionPatch,
  SessionSetup,
} from "./types";

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
