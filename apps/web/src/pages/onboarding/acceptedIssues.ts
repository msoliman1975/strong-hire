/**
 * IN-12: which CV-check issues the user accepted, stored on the resume (`accepted_issues`,
 * PUT /resumes/{id}/accepted-issues). The page only uses this interface. Changes show at once
 * and roll back if the save fails.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import { keys as queryKeys } from "../../api/hooks";
import { resumesApi } from "../../api/inputs";

/** The most keys a resume keeps (the API enforces the same limit). */
export const MAX_ACCEPTED = 100;

export interface AcceptedIssues {
  keys: ReadonlySet<string>;
  accept: (key: string) => void;
  undo: (key: string) => void;
  /** The last failed save, cleared by the next change. */
  error: unknown;
}

function toggle(set: ReadonlySet<string>, key: string, on: boolean): ReadonlySet<string> {
  if (set.has(key) === on) return set;
  const next = new Set(set);
  if (on) next.add(key);
  else next.delete(key);
  return next;
}

export function useAcceptedIssues(resumeId: string, initial: readonly { key: string }[] = []): AcceptedIssues {
  const queryClient = useQueryClient();
  const [keys, setKeys] = useState<ReadonlySet<string>>(() => new Set(initial.map((i) => i.key)));
  const [error, setError] = useState<unknown>(null);

  const send = useCallback(
    async (key: string, accepted: boolean) => {
      setError(null);
      setKeys((prev) => toggle(prev, key, accepted));
      try {
        const record = await resumesApi.setAcceptedIssue(resumeId, key, accepted);
        queryClient.setQueryData(queryKeys.resume(resumeId), record);
      } catch (e) {
        setKeys((prev) => toggle(prev, key, !accepted));
        setError(e);
      }
    },
    [resumeId, queryClient],
  );

  const accept = useCallback(
    (key: string) => {
      if (keys.size >= MAX_ACCEPTED && !keys.has(key)) {
        setError(new Error(`You can accept up to ${MAX_ACCEPTED} issues on one CV.`));
        return;
      }
      void send(key, true);
    },
    [keys, send],
  );
  const undo = useCallback((key: string) => void send(key, false), [send]);
  return useMemo(() => ({ keys, accept, undo, error }), [keys, accept, undo, error]);
}
