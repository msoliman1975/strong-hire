/**
 * Opening the Custom setup prefilled: "Run this setup again" from the debrief and the rehearsals
 * view (CU-9), and a recommended Custom session (CU-10). Both use the router state of
 * SessionSetupPage (`SetupState`).
 */
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { customApi } from "../api/custom";
import type { CustomRecommendation, SessionSetup } from "../api/types";

/** Router state that prefills the setup page. */
export interface SetupState {
  /** CU-9: an earlier session's setup. */
  setup?: SessionSetup;
  /** CU-10: a recommended Custom session. */
  recommended?: CustomRecommendation;
}

export function setupPath(jobId: string, resumeId?: string | null): string {
  const query = resumeId ? `?resume=${encodeURIComponent(resumeId)}` : "";
  return `/jobs/${jobId}/sessions/new${query}`;
}

/**
 * CU-9: fetch an earlier session's setup and open the setup screen with it. The setup keeps the
 * categories, focus chips and own questions; the interviewer's questions are drawn fresh.
 */
export function useRepeatSetup() {
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (sessionId: string) => customApi.repeat(sessionId),
    onSuccess: (setup) => {
      const state: SetupState = { setup };
      navigate(setupPath(setup.job_target_id, setup.resume_id), { state });
    },
  });
}

/** A focus chip inside a sentence: "Conflict handling" reads "conflict handling", "Kubernetes" stays. */
function inSentence(topic: string): string {
  return /^[A-Z][a-z]+( [a-z][\w-]*)+$/.test(topic) ? topic.charAt(0).toLowerCase() + topic.slice(1) : topic;
}

/** CU-10: "Practice conflict handling and Kubernetes". */
export function practiceTitle(rec: CustomRecommendation): string {
  const topics = rec.focus_topics.map(inSentence);
  const list = topics.length > 1 ? `${topics.slice(0, -1).join(", ")} and ${topics[topics.length - 1]}` : topics[0];
  return `Practice ${list}`;
}
