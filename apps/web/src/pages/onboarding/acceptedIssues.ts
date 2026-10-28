/**
 * IN-12: which CV-check issues the user accepted. The page only uses this interface, so the
 * store can move from component state to the API (`accepted_issues` on the resume) without
 * touching the page.
 */
import { useCallback, useMemo, useState } from "react";

/** The most keys a resume keeps (the API enforces the same limit). */
export const MAX_ACCEPTED = 100;

export interface AcceptedIssues {
  keys: ReadonlySet<string>;
  accept: (key: string) => void;
  undo: (key: string) => void;
}

/** Accepted issues held in component state, starting from `initial`. Lost on reload. */
export function useAcceptedIssues(initial: readonly string[] = []): AcceptedIssues {
  const [keys, setKeys] = useState<ReadonlySet<string>>(() => new Set(initial.slice(0, MAX_ACCEPTED)));
  const accept = useCallback(
    (key: string) =>
      setKeys((prev) => (prev.has(key) || prev.size >= MAX_ACCEPTED ? prev : new Set([...prev, key]))),
    [],
  );
  const undo = useCallback(
    (key: string) =>
      setKeys((prev) => {
        if (!prev.has(key)) return prev;
        const next = new Set(prev);
        next.delete(key);
        return next;
      }),
    [],
  );
  return useMemo(() => ({ keys, accept, undo }), [keys, accept, undo]);
}
