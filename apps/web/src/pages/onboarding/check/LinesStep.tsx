/**
 * RSD-12 (RM-3, SG-6): step 4, "Stronger resume lines". Strova's rewrites of a resume line from a
 * story's result, one at a time: the source story, the before and after, Add to resume (then Undo)
 * and Dismiss. After Add or Undo the page reloads the saved resume, so step 1 shows the new line.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { suggestionKeys, suggestionsApi, useSuggestions } from "../../../api/suggestions";
import type { Suggestion } from "../../../api/types";
import { ErrorNotice, Loading } from "../../../components/ui";
import { useStories } from "../../stories/api";

export const NO_REWRITES = "No rewrites yet. Strova suggests one when a story has a result your resume leaves out.";

export function LinesStep({ resumeId, onResumeChanged }: { resumeId: string; onResumeChanged: () => void }) {
  const list = useSuggestions("resume", { resume_id: resumeId });
  const stories = useStories();
  const [index, setIndex] = useState(0);
  const lines = (list.data ?? []).filter((s) => s.kind === "improve_resume_line");
  const i = Math.min(index, Math.max(0, lines.length - 1));
  const line = lines[i];
  const title = (s: Suggestion) => (s.story_id ? stories.data?.find((x) => x.id === s.story_id)?.title : undefined);

  return (
    <section className="cvc-step-view cvc-lines" aria-labelledby="cvc-lines-h" data-testid="lines-step">
      <h2 id="cvc-lines-h" className="visually-hidden">
        Stronger resume lines
      </h2>
      {list.isPending && <Loading label="Loading Strova's rewrites" />}
      {list.isError && <ErrorNotice error={list.error} />}
      {list.data && !line && (
        <div className="cvc-card cvc-clear">
          <p>{NO_REWRITES}</p>
        </div>
      )}
      {line && (
        <LineCard
          key={line.id}
          suggestion={line}
          storyTitle={title(line)}
          position={`Line ${i + 1} of ${lines.length}`}
          resumeId={resumeId}
          onResumeChanged={onResumeChanged}
          nav={
            lines.length > 1 && (
              <span className="cvc-finding__nav">
                <button type="button" className="sx-btn quiet sm" aria-label="Previous line" disabled={i <= 0} onClick={() => setIndex(i - 1)}>
                  ‹
                </button>
                <button
                  type="button"
                  className="sx-btn quiet sm"
                  aria-label="Next line"
                  disabled={i >= lines.length - 1}
                  onClick={() => setIndex(i + 1)}
                >
                  ›
                </button>
              </span>
            )
          }
        />
      )}
    </section>
  );
}

function LineCard({
  suggestion,
  storyTitle,
  position,
  resumeId,
  onResumeChanged,
  nav,
}: {
  suggestion: Suggestion;
  storyTitle?: string;
  position: string;
  resumeId: string;
  onResumeChanged: () => void;
  nav: ReactNode;
}) {
  const client = useQueryClient();
  const [added, setAdded] = useState(false);
  const refreshList = () => void client.invalidateQueries({ queryKey: suggestionKeys.place("resume", resumeId) });
  const accept = useMutation({
    mutationFn: () => suggestionsApi.accept(suggestion.id),
    onSuccess: () => {
      setAdded(true);
      void client.invalidateQueries({ queryKey: ["resumes"] });
      onResumeChanged();
    },
  });
  const undo = useMutation({
    mutationFn: () => suggestionsApi.undo(suggestion.id),
    onSuccess: () => {
      setAdded(false);
      void client.invalidateQueries({ queryKey: ["resumes"] });
      onResumeChanged();
    },
  });
  const dismiss = useMutation({ mutationFn: () => suggestionsApi.dismiss(suggestion.id), onSuccess: refreshList });
  const error = accept.error ?? undo.error ?? dismiss.error;
  const busy = accept.isPending || undo.isPending || dismiss.isPending;
  const p = suggestion.payload;
  if (p.kind !== "improve_resume_line") return null;
  return (
    <section className="cvc-card cvc-finding cvc-line" aria-label="Strova suggests a resume line" data-testid="resume-line-suggestion">
      <div className="cvc-finding__top">
        <span className="cvc-top__title">
          <span className="cvc-label">{position}</span>
          <span className="cvc-step__tag">Your stories → Resume</span>
        </span>
        {nav}
      </div>
      <span className="sx-eyebrow">Strova suggests · from your stories</span>
      <p className="cvc-finding__detail">
        {storyTitle
          ? `You told Strova a result in your story "${storyTitle}" that your resume leaves out. Here is the line with it.`
          : suggestion.reason}
      </p>
      {added ? (
        <div className="sx-notice ok sx-small" role="status">
          <strong>Added to your resume.</strong>{" "}
          <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => undo.mutate()}>
            Undo
          </button>
        </div>
      ) : (
        <>
          <div className="sx-diff">
            <del>{p.before}</del>
            <br />
            <ins>{p.after}</ins>
          </div>
          <div className="row cvc-finding__actions">
            <button type="button" className="btn btn--small" disabled={busy} onClick={() => accept.mutate()}>
              Add to resume
            </button>
            <button type="button" className="btn btn--secondary btn--small" disabled={busy} onClick={() => dismiss.mutate()}>
              Dismiss
            </button>
          </div>
        </>
      )}
      {error && <ErrorNotice error={error} />}
    </section>
  );
}
