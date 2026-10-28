/** TR-1: GET /sessions/{id}/transcript, the turns of a finished session grouped by question. */
import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "../../api/client";
import type { components } from "../../api/schema.gen";

export type Transcript = components["schemas"]["Transcript"];
export type TranscriptGroup = components["schemas"]["TranscriptGroup"];
export type TranscriptTurn = components["schemas"]["TranscriptTurn"];

export const transcriptApi = {
  get: async (sessionId: string) =>
    unwrap(
      await apiClient.GET("/sessions/{session_id}/transcript", { params: { path: { session_id: sessionId } } }),
    ) as Transcript,
};

export const transcriptKey = (sessionId: string) => ["sessions", sessionId, "transcript"] as const;

/** A finished transcript does not change, so it is not refetched. */
export const useTranscript = (sessionId: string) =>
  useQuery({
    queryKey: transcriptKey(sessionId),
    queryFn: () => transcriptApi.get(sessionId),
    staleTime: Infinity,
    enabled: sessionId !== "",
  });
