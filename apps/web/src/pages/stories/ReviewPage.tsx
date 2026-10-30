/**
 * ST-11 (mockup #review): Review with Strova. The story's parts on the left; on the right, the
 * ask panel, then Strova's review: a summary, a before-and-after edit per part to Accept or Skip
 * (the edits use the user's own words, U08), and the missing parts with "Answer with Strova",
 * which continues crafting on this story at the first missing part.
 *
 * POST /stories/{id}/review queues the review; it arrives as the story's open `review`
 * suggestion, which this page polls for.
 */
import "../../components/ux/ux.css";
import "./stories.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { suggestionsApi } from "../../api/suggestions";
import type { Suggestion } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading, STORY_PART_LABEL } from "../../components/ui";
import { newCoachPath } from "../coach/paths";
import { STORY_PARTS, storiesApi, storyKeys, useStory, type Story } from "./api";
import { storyPath } from "./paths";

const POLL_MS = 1500;

const reviewKey = (storyId: string) => ["suggestions", "story", storyId, "review"] as const;

type Review = Extract<Suggestion["payload"], { kind: "review" }>["review"];

/** The story's open review suggestion, polled while one is on its way. */
function useReview(storyId: string, waiting: boolean) {
  return useQuery({
    queryKey: reviewKey(storyId),
    queryFn: async () =>
      (await suggestionsApi.list("story", { story_id: storyId })).find((s) => s.kind === "review") ?? null,
    refetchInterval: (q) => (waiting && !q.state.data ? POLL_MS : false),
  });
}

export function ReviewPage() {
  const { storyId = "" } = useParams();
  const story = useStory(storyId);
  const [requested, setRequested] = useState(false);
  const review = useReview(storyId, requested);
  // Keep the review once seen: it closes on the server when its last edit is accepted.
  const [seen, setSeen] = useState<Suggestion | null>(null);
  if (review.data && review.data.id !== seen?.id) setSeen(review.data);
  const client = useQueryClient();
  const ask = useMutation({
    mutationFn: () => storiesApi.review(storyId),
    onSuccess: () => {
      setRequested(true);
      void client.invalidateQueries({ queryKey: reviewKey(storyId) });
    },
  });

  if (story.isPending) return <Loading label="Loading the story" />;
  if (story.isError) return <ErrorNotice error={story.error} />;
  const s = story.data;
  const current = seen ?? review.data ?? null;
  const analysing = !current && (requested || ask.isPending);
  return (
    <div className="sx-page">
      <Link to={storyPath(s.id)} className="sx-small">
        Back to the story
      </Link>
      <div className="sx-stack">
        <div className="sx-eyebrow">Review with Strova</div>
        <h1>{s.title}</h1>
        <p className="sx-small sx-muted">
          {s.source === "manual" ? "You wrote this story. " : ""}Strova reviews it part by part.
        </p>
      </div>
      <div className="sx-grid2 review-grid">
        <section className="sx-card" aria-label="Story parts">
          {STORY_PARTS.map((p) => (
            <div key={p} className="sx-part" data-testid={`part-${p}`}>
              <span className="part-lbl" data-part={p}>
                {s[p]?.trim() ? "●" : "○"} {STORY_PART_LABEL[p]}
              </span>
              {s[p]?.trim() ? <span>{s[p]}</span> : <span className="sx-muted">Not written yet</span>}
            </div>
          ))}
          {!current && !analysing && (
            <div className="sx-row">
              <button type="button" className="sx-btn" disabled={ask.isPending} onClick={() => ask.mutate()}>
                Review with Strova
              </button>
              <Link className="sx-btn ghost" to={newCoachPath({ story: s.id })}>
                Craft the rest with Strova
              </Link>
            </div>
          )}
          {ask.isError && <ErrorNotice error={ask.error} />}
        </section>
        <section className="sx-card coach" aria-label="Strova's review" role="region">
          {current && current.payload.kind === "review" ? (
            <ReviewResult suggestion={current} review={current.payload.review} story={s} />
          ) : analysing ? (
            <div className="sx-row" role="status">
              <Strova mode="analysing" size={72} />
              <span className="sx-small sx-muted">Strova is reviewing your story part by part.</span>
            </div>
          ) : (
            <>
              <div className="sx-row">
                <Strova mode="coaching" size={28} />
                <h3>Ask Strova to review</h3>
              </div>
              <p className="sx-small sx-muted">
                Strova checks each part against what interviewers look for: your own role, a measurable result,
                trade-offs and what you learned. Suggested edits use your own words, and you accept or skip each one.
              </p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function ReviewResult({ suggestion, review, story }: { suggestion: Suggestion; review: Review; story: Story }) {
  const client = useQueryClient();
  const [applied, setApplied] = useState<string[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]);
  const accept = useMutation({
    mutationFn: (part: string) =>
      suggestionsApi.accept(suggestion.id, { parts: [part as (typeof STORY_PARTS)[number]] }),
    onSuccess: (_out, part) => {
      setApplied((a) => [...a, part]);
      void client.invalidateQueries({ queryKey: storyKeys.all });
    },
  });
  const firstMissing = STORY_PARTS.find((p) => !story[p]?.trim());
  return (
    <>
      <div className="sx-row">
        <Strova mode="analysing" size={72} />
        <h3>Strova's review</h3>
      </div>
      <div className="sx-notice ok sx-small">{review.summary}</div>
      {accept.isError && <ErrorNotice error={accept.error} />}
      {review.notes.map((n) => {
        const label = STORY_PART_LABEL[n.part];
        if (n.edit) {
          if (applied.includes(n.part))
            return (
              <div key={n.part} className="sx-notice ok sx-small" role="status">
                <strong>{label} updated.</strong>
              </div>
            );
          if (skipped.includes(n.part)) return null;
          return (
            <div key={n.part} className="sx-card tight" role="group" aria-label={`Edit to ${label}`}>
              <span className="sx-eyebrow">{label}</span>
              <span className="sx-small">{n.note}</span>
              <div className="sx-diff">
                {n.edit.before && (
                  <>
                    <del>{n.edit.before}</del>
                    <br />
                  </>
                )}
                <ins>{n.edit.after}</ins>
              </div>
              <div className="sx-row">
                <button
                  type="button"
                  className="sx-btn sm"
                  disabled={accept.isPending}
                  onClick={() => accept.mutate(n.part)}
                >
                  Accept
                </button>
                <button type="button" className="sx-btn quiet sm" onClick={() => setSkipped((s) => [...s, n.part])}>
                  Skip
                </button>
              </div>
            </div>
          );
        }
        const empty = !story[n.part]?.trim();
        return (
          <div key={n.part} className={`sx-notice ${empty ? "warn" : "v"} sx-small`} data-testid={`note-${n.part}`}>
            <strong>{empty ? `${label} is missing.` : label}</strong> {n.note}{" "}
            {empty && firstMissing && (
              <Link to={newCoachPath({ story: story.id })} className="sx-small">
                Answer with Strova
              </Link>
            )}
          </div>
        );
      })}
    </>
  );
}
