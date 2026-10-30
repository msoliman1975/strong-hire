/**
 * IN-12: which CV-check issues the user accepted, stored on the resume (`accepted_issues`,
 * PUT /resumes/{id}/accepted-issues). The page only uses this interface. Changes show at once
 * and roll back if the save fails.
 *
 * An issue can be accepted with a reason (IN-12, missing dates): the stored key is then the issue
 * key plus `|why=<reason>`, for example `dates.missing-start:acme/engineer|why=on-purpose`. The
 * API treats keys as opaque, so no contract change is needed.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import { keys as queryKeys } from "../../api/hooks";
import { resumesApi } from "../../api/inputs";
import { KEY_MAX } from "./resumeChecks";

/** The most keys a resume keeps (the API enforces the same limit). */
export const MAX_ACCEPTED = 100;

const WHY = "|why=";

/** The stored key for an issue key and an optional reason. Too long for the API: no reason. */
export function storedKey(key: string, reason?: string | null): string {
  const withReason = reason ? `${key}${WHY}${reason}` : key;
  return withReason.length <= KEY_MAX ? withReason : key;
}

/** Splits a stored key into the issue key and its reason, if any. */
export function parseStoredKey(stored: string): { key: string; reason: string | null } {
  const at = stored.lastIndexOf(WHY);
  return at < 0 ? { key: stored, reason: null } : { key: stored.slice(0, at), reason: stored.slice(at + WHY.length) };
}

/** The issue keys in a resume's `accepted_issues`, reasons dropped. */
export const acceptedKeySet = (list: readonly { key: string }[]): Set<string> =>
  new Set(list.map((i) => parseStoredKey(i.key).key));

export interface AcceptedIssues {
  /** Accepted issue keys, without reasons. */
  keys: ReadonlySet<string>;
  /** The reason an issue was accepted with, if any. */
  reasons: ReadonlyMap<string, string>;
  accept: (key: string, reason?: string) => void;
  undo: (key: string) => void;
  /** The last failed save, cleared by the next change. */
  error: unknown;
}

/** Issue key to stored key. */
type Stored = ReadonlyMap<string, string>;

function toggle(map: Stored, key: string, stored: string | null): Stored {
  if ((map.get(key) ?? null) === stored) return map;
  const next = new Map(map);
  if (stored) next.set(key, stored);
  else next.delete(key);
  return next;
}

export function useAcceptedIssues(resumeId: string, initial: readonly { key: string }[] = []): AcceptedIssues {
  const queryClient = useQueryClient();
  const [stored, setStored] = useState<Stored>(() => new Map(initial.map((i) => [parseStoredKey(i.key).key, i.key])));
  const [error, setError] = useState<unknown>(null);

  /** Stores `next` for `key` (null clears it): clears the old stored key first when it differs. */
  const send = useCallback(
    async (key: string, next: string | null, previous: string | null) => {
      setError(null);
      setStored((prev) => toggle(prev, key, next));
      try {
        let record = null;
        if (previous && previous !== next) record = await resumesApi.setAcceptedIssue(resumeId, previous, false);
        if (next) record = await resumesApi.setAcceptedIssue(resumeId, next, true);
        if (record) queryClient.setQueryData(queryKeys.resume(resumeId), record);
        // The Resumes list and the Home card summarize the accepted issues too.
        void queryClient.invalidateQueries({ queryKey: queryKeys.resumes, exact: true });
      } catch (e) {
        setStored((prev) => toggle(prev, key, previous));
        setError(e);
      }
    },
    [resumeId, queryClient],
  );

  const accept = useCallback(
    (key: string, reason?: string) => {
      if (stored.size >= MAX_ACCEPTED && !stored.has(key)) {
        setError(new Error(`You can accept up to ${MAX_ACCEPTED} issues on one resume.`));
        return;
      }
      void send(key, storedKey(key, reason), stored.get(key) ?? null);
    },
    [stored, send],
  );
  const undo = useCallback((key: string) => void send(key, null, stored.get(key) ?? null), [stored, send]);
  return useMemo(() => {
    const keys = new Set(stored.keys());
    const reasons = new Map<string, string>();
    for (const [key, raw] of stored) {
      const { reason } = parseStoredKey(raw);
      if (reason) reasons.set(key, reason);
    }
    return { keys, reasons, accept, undo, error };
  }, [stored, accept, undo, error]);
}
