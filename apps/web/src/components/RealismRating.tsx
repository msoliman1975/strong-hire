import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { feedbackApi } from "../api/feedback";
import { ErrorNotice } from "./ui";

const SCORES = [1, 2, 3, 4, 5] as const;
const SKIP_KEY = (sessionId: string) => `strong-hire-rating-skipped:${sessionId}`;

function readSkipped(sessionId: string): boolean {
  try {
    return globalThis.localStorage?.getItem(SKIP_KEY(sessionId)) === "1";
  } catch {
    return false;
  }
}

/**
 * L05: one question after the interview, "felt like a real interview", 1 to 5, with an optional
 * comment. Shown until the candidate rates or skips; skipping stores nothing on the server.
 */
export function RealismRating({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const key = ["sessions", sessionId, "feedback"];
  const feedback = useQuery({ queryKey: key, queryFn: () => feedbackApi.get(sessionId) });
  const [skipped, setSkipped] = useState(() => readSkipped(sessionId));
  const [score, setScore] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const save = useMutation({
    mutationFn: (realism: number) => feedbackApi.put(sessionId, { realism, comment: comment.trim() || null }),
    onSuccess: (data) => queryClient.setQueryData(key, data),
  });

  if (save.isSuccess) {
    return (
      <section className="panel rating" aria-label="Your rating">
        <p>Thanks. You rated this interview {save.data.realism} of 5.</p>
      </section>
    );
  }
  if (feedback.isPending || feedback.isError || feedback.data || skipped) return null;

  const skip = () => {
    try {
      globalThis.localStorage?.setItem(SKIP_KEY(sessionId), "1");
    } catch {
      // Private mode: the question comes back on the next visit.
    }
    setSkipped(true);
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (score !== null) save.mutate(score);
  };

  return (
    <form className="panel rating" onSubmit={onSubmit} aria-labelledby="rating-title">
      <h2 id="rating-title" className="rating__title">
        How real did it feel?
      </h2>
      <fieldset>
        <legend>How much did this feel like a real interview? 1 is not at all, 5 is just like one.</legend>
        <div className="rating__scores">
          {SCORES.map((n) => (
            <label key={n} className="rating__score">
              <input type="radio" name="realism" value={n} checked={score === n} onChange={() => setScore(n)} />
              <span>{n}</span>
            </label>
          ))}
        </div>
      </fieldset>
      {score !== null && (
        <div className="field">
          <label htmlFor="rating-comment">What felt off? (optional)</label>
          <textarea
            id="rating-comment"
            rows={2}
            maxLength={2000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>
      )}
      {save.isError && <ErrorNotice error={save.error} />}
      <div className="row">
        <button type="submit" className="btn" disabled={score === null || save.isPending}>
          Send rating
        </button>
        <button type="button" className="btn btn--quiet" onClick={skip}>
          Skip
        </button>
      </div>
    </form>
  );
}
