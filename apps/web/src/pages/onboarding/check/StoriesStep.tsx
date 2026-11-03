/**
 * RSD-11 (RM-3, RM-4): step 3, "Stories to tell in interviews". Strova's story ideas from this
 * resume, one at a time: the achievement, its skills, what it still needs, Craft with Strova and
 * Not a story (persists). "Already crafted" links each story made from a line.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { keys, useStoryIdeas } from "../../../api/hooks";
import { resumesApi } from "../../../api/inputs";
import { ErrorNotice, Loading } from "../../../components/ui";
import { competencyLabel } from "../../../labels";
import { storyPath } from "../../stories/paths";

/** Craft with Strova, seeded with this achievement (U10 reads `idea` and `resume`). */
export const craftFromIdeaPath = (resumeId: string, ref: string) =>
  `/coach/new?resume=${encodeURIComponent(resumeId)}&idea=${encodeURIComponent(ref)}`;

const PART: Record<string, string> = {
  context: "context",
  stakes: "stakes",
  action: "your action",
  result: "result",
  reflection: "reflection",
};

export function StoriesStep({ resumeId }: { resumeId: string }) {
  const ideas = useStoryIdeas(resumeId);
  const client = useQueryClient();
  const [index, setIndex] = useState(0);
  const dismiss = useMutation({
    mutationFn: (ref: string) => resumesApi.dismissIdea(resumeId, ref),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.storyIdeas(resumeId) });
      void client.invalidateQueries({ queryKey: ["resumes"] });
    },
  });
  const list = ideas.data?.ideas ?? [];
  const used = ideas.data?.used ?? [];
  const i = Math.min(index, Math.max(0, list.length - 1));
  const idea = list[i];

  return (
    <section className="cvc-step-view cvc-stories" aria-labelledby="cvc-stories-h" data-testid="stories-step">
      <h2 id="cvc-stories-h" className="visually-hidden">
        Stories to tell in interviews
      </h2>
      {ideas.isPending && <Loading label="Loading Strova's story ideas" />}
      {ideas.isError && <ErrorNotice error={ideas.error} />}
      {dismiss.isError && <ErrorNotice error={dismiss.error} />}
      {ideas.data && !idea && (
        <div className="cvc-card cvc-clear">
          <p>No ideas left. Every achievement is a story or was set aside.</p>
        </div>
      )}
      {idea && (
        <article className="cvc-card cvc-finding cvc-idea" aria-labelledby="cvc-idea-h">
          <div className="cvc-finding__top">
            <span className="cvc-top__title">
              <span className="cvc-label" data-testid="idea-position">
                Story {i + 1} of {list.length}
              </span>
              <span className="cvc-step__tag">Resume → Interview</span>
            </span>
            <span className="cvc-finding__nav">
              <button type="button" className="sx-btn quiet sm" aria-label="Previous idea" disabled={i <= 0} onClick={() => setIndex(i - 1)}>
                ‹
              </button>
              <button
                type="button"
                className="sx-btn quiet sm"
                aria-label="Next idea"
                disabled={i >= list.length - 1}
                onClick={() => setIndex(i + 1)}
              >
                ›
              </button>
            </span>
          </div>
          <p className="cvc-finding__detail">
            This achievement could answer a behavioral question. Craft it once with Strova and reuse it in every interview.
          </p>
          <h3 id="cvc-idea-h" className="cvc-finding__title">
            {idea.achievement}
          </h3>
          <div className="sx-chips">
            {idea.skills.map((s) => (
              <span key={s} className="sx-chip v">
                {competencyLabel(s)}
              </span>
            ))}
            {idea.missing_parts.length > 0 && (
              <span className="sx-small sx-muted">Still needs: {idea.missing_parts.map((p) => PART[p] ?? p).join(", ")}</span>
            )}
          </div>
          <div className="row cvc-finding__actions">
            <Link className="btn btn--small" to={craftFromIdeaPath(resumeId, idea.resume_line_ref)}>
              Craft with Strova
            </Link>
            <button
              type="button"
              className="btn btn--secondary btn--small"
              disabled={dismiss.isPending}
              onClick={() => dismiss.mutate(idea.resume_line_ref)}
            >
              Not a story
            </button>
          </div>
        </article>
      )}
      {used.length > 0 && (
        <div className="cvc-next-findings">
          <p className="cvc-label">Already crafted · {used.length}</p>
          <ul className="cvc-finding-rows" aria-label="Already crafted">
            {used.map((u) => (
              <li key={u.resume_line_ref} className="cvc-card cvc-finding-row">
                <span className="muted">{u.achievement}</span>
                <Link to={storyPath(u.story_id)}>Story: {u.story_title}</Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
