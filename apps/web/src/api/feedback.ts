/**
 * The post-session rating (L05): "felt like a real interview", 1 to 5. GET answers null until
 * the candidate rates the session; PUT rates it or changes the rating.
 */
import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

export type SessionFeedbackIn = components["schemas"]["SessionFeedbackIn"];
export type SessionFeedback = components["schemas"]["SessionFeedbackOut"];

export const feedbackApi = {
  get: async (sessionId: string) =>
    (unwrap(
      await apiClient.GET("/sessions/{session_id}/feedback", { params: { path: { session_id: sessionId } } }),
    ) ?? null) as SessionFeedback | null,
  put: async (sessionId: string, body: SessionFeedbackIn) =>
    unwrap(
      await apiClient.PUT("/sessions/{session_id}/feedback", { params: { path: { session_id: sessionId } }, body }),
    ) as SessionFeedback,
};
