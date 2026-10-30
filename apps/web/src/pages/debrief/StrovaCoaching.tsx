/**
 * DB-4 (mockup #debrief): Strova's coaching, back on the candidate's side. One coaching sentence,
 * then this take's suggestions (U08): tune a story with its before-and-after (Apply, Edit first,
 * Dismiss, then Undo), new story (Save as a story), missing skill (Craft it with Strova). DB-5:
 * a story this take made Proven is celebrated. DB-6: the plan's next item, once the plan has one.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { suggestionsApi } from "../../api/suggestions";
import type { Debrief, QuestionScore, Scorecard, Suggestion } from "../../api/types";
import { Strova } from "../../components/strova";
import { competencyLabel } from "../../labels";
import { newCoachPath } from "../coach/paths";
import { storyPath } from "../stories/paths";
import { answerAverage, BAR_SCORE } from "./AnswerList";
import { storiesKey, useStories, type Story } from "./StoryApi";

const PART_LABEL: Record<string, string> = {
  context: "Context",
  stakes: "Stakes",
  action: "Your action",
  result: "Result",
  reflection: "Reflection",
};

/** One coaching sentence from the scores: the strongest skill, then the one to work on. */
export function coachingLine(scorecard: Scorecard): string {
  const scores = [...scorecard.competency_scores].sort((a, b) => b.score - a.score);
  const best = scores[0];
  const weakest = scores.at(-1);
  if (!best) return "Here is what I suggest:";
  const shown = `You showed ${competencyLabel(best.competency).toLowerCase()}.`;
  if (!weakest || weakest === best || weakest.score >= BAR_SCORE)
    return `${shown} Keep that up in the next take. Here is what I suggest:`;
  return `${shown} Next, work on ${competencyLabel(weakest.competency).toLowerCase()}. Here is what I suggest:`;
}

/** DB-5: the stories this take made Proven: used by a Realistic answer that met the bar, and Proven now. */
export function provenByTake(debrief: Debrief, scorecard: Scorecard, stories: Story[]): Story[] {
  if (debrief.session.config.mode !== "realistic") return [];
  const ids = new Set(
    scorecard.per_question
      .filter((q: QuestionScore) => q.story_id && (answerAverage(q) ?? 0) >= BAR_SCORE)
      .map((q) => q.story_id as string),
  );
  return stories.filter((s) => ids.has(s.id) && s.status === "proven");
}

function answerNumber(scorecard: Scorecard, ref: string | null): number | null {
  const i = scorecard.per_question.findIndex((q) => q.question_ref === ref);
  return i < 0 ? null : i + 1;
}

export function StrovaCoaching({ debrief, scorecard }: { debrief: Debrief; scorecard: Scorecard }) {
  const stories = useStories();
  const library = stories.data ?? [];
  const [open, setOpen] = useState<Suggestion[]>(debrief.suggestions);
  const proven = provenByTake(debrief, scorecard, library);
  const remove = (id: string) => setOpen((list) => list.filter((s) => s.id !== id));
  return (
    <section className="sx-card coach debrief-coaching" aria-labelledby="debrief-coaching-heading">
      <div className="sx-row">
        <Strova mode="coaching" size={72} />
        <div>
          <h2 id="debrief-coaching-heading">Strova's coaching</h2>
          <span className="sx-small sx-muted">Back on your side: what to do next</span>
        </div>
      </div>
      <p>{coachingLine(scorecard)}</p>
      {open.length === 0 && <p className="sx-small sx-muted">Nothing to change from this take.</p>}
      {open.map((s) => (
        <SuggestionCard
          key={s.id}
          suggestion={s}
          scorecard={scorecard}
          library={library}
          onGone={() => remove(s.id)}
        />
      ))}
      {proven.map((story) => (
        <div key={story.id} className="sx-notice ok sx-row" role="status" data-testid="proven">
          <Strova mode="celebrating" size={72} />
          <span>
            <strong>{story.title} is now Proven.</strong> It met the bar in a Realistic take.
          </span>
        </div>
      ))}
      {debrief.next_plan_item && (
        <div className="sx-between debrief-coaching__plan" data-testid="plan-line">
          <span>
            <strong>Your plan updated:</strong> next is {debrief.next_plan_item}
          </span>
          <Link className="sx-btn dark sm" to="/">
            Back to Home
          </Link>
        </div>
      )}
    </section>
  );
}

function SuggestionCard({
  suggestion,
  scorecard,
  library,
  onGone,
}: {
  suggestion: Suggestion;
  scorecard: Scorecard;
  library: Story[];
  onGone: () => void;
}) {
  const client = useQueryClient();
  const [applied, setApplied] = useState<{ storyId: string | null } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const done = () => void client.invalidateQueries({ queryKey: storiesKey });
  const accept = useMutation({
    mutationFn: (after?: string) => suggestionsApi.accept(suggestion.id, after ? { after } : {}),
    onSuccess: (out) => {
      done();
      setEditing(null);
      setApplied({ storyId: out.story_id });
    },
  });
  const dismiss = useMutation({ mutationFn: () => suggestionsApi.dismiss(suggestion.id), onSuccess: onGone });
  const undo = useMutation({
    mutationFn: () => suggestionsApi.undo(suggestion.id),
    onSuccess: () => {
      done();
      setApplied(null);
    },
  });
  const error = accept.error ?? dismiss.error ?? undo.error;
  const busy = accept.isPending || dismiss.isPending || undo.isPending;
  const p = suggestion.payload;
  const answer = answerNumber(scorecard, suggestion.source_question_ref);
  const errorLine = error && (
    <span className="sx-small" role="alert">
      {error.message}
    </span>
  );

  if (p.kind === "tune_story") {
    const story = library.find((s) => s.id === suggestion.story_id);
    const title = story?.title ?? "your story";
    if (applied) {
      return (
        <div className="sx-notice ok" role="status" data-testid="applied">
          <strong>Applied to “{title}”.</strong>{" "}
          {suggestion.story_id && <Link to={storyPath(suggestion.story_id)}>See the story</Link>} ·{" "}
          <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => undo.mutate()}>
            Undo
          </button>
          {errorLine}
        </div>
      );
    }
    return (
      <div className="sx-card tight" role="group" aria-label={`Tune a story: ${title}`} data-testid="suggestion">
        <span className="sx-eyebrow">Tune a story · {title}</span>
        <span>
          {answer ? `From answer ${answer}: ` : ""}
          {suggestion.reason}
        </span>
        {editing === null ? (
          <div className="sx-diff">
            <span className="sx-small sx-muted">{PART_LABEL[p.edit.part]}</span>
            <br />
            {p.edit.before && (
              <>
                <del>{p.edit.before}</del>
                <br />
              </>
            )}
            <ins>{p.edit.after}</ins>
          </div>
        ) : (
          <label className="sx-field">
            <span>{PART_LABEL[p.edit.part]}</span>
            <textarea rows={3} value={editing} onChange={(e) => setEditing(e.target.value)} />
          </label>
        )}
        <div className="sx-row">
          {editing === null ? (
            <>
              <button type="button" className="sx-btn sm" disabled={busy} onClick={() => accept.mutate(undefined)}>
                Apply
              </button>
              <button type="button" className="sx-btn ghost sm" disabled={busy} onClick={() => setEditing(p.edit.after)}>
                Edit first
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="sx-btn sm"
                disabled={busy || !editing.trim()}
                onClick={() => accept.mutate(editing.trim())}
              >
                Apply my edit
              </button>
              <button type="button" className="sx-btn ghost sm" disabled={busy} onClick={() => setEditing(null)}>
                Cancel
              </button>
            </>
          )}
          <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => dismiss.mutate()}>
            Dismiss
          </button>
        </div>
        {errorLine}
      </div>
    );
  }

  if (p.kind === "new_story") {
    if (applied) {
      return (
        <div className="sx-notice ok" role="status" data-testid="applied">
          <strong>Saved “{p.title}” as a Draft story.</strong>{" "}
          {applied.storyId && <Link to={storyPath(applied.storyId)}>Open the story</Link>}
        </div>
      );
    }
    return (
      <div className="sx-card tight sx-sugg" role="group" aria-label={`New story: ${p.title}`} data-testid="suggestion">
        <div className="txt">
          <span className="sx-eyebrow debrief-coaching__ok">New story{answer ? ` · from answer ${answer}` : ""}</span>
          <span>
            “{p.title}”. {suggestion.reason}
          </span>
          {errorLine}
        </div>
        <div className="sx-row">
          <button type="button" className="sx-btn ghost sm" disabled={busy} onClick={() => accept.mutate(undefined)}>
            Save as a story
          </button>
          <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => dismiss.mutate()}>
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  if (p.kind === "missing_skill") {
    const skill = competencyLabel(p.competency);
    return (
      <div className="sx-card tight sx-sugg" role="group" aria-label={`Missing skill: ${skill}`} data-testid="suggestion">
        <div className="txt">
          <span className="sx-eyebrow warn">Missing skill · {skill}</span>
          <span>{suggestion.reason} Let's find one together.</span>
          {errorLine}
        </div>
        <div className="sx-row">
          <Link className="sx-btn ghost sm" to={newCoachPath({ skill: p.competency, job: suggestion.job_target_id ?? undefined })}>
            Craft it with Strova
          </Link>
          <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => dismiss.mutate()}>
            Dismiss
          </button>
        </div>
      </div>
    );
  }
  return null;
}
