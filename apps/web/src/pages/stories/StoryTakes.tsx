/**
 * CO-7 (UI): the story's takes as a timeline (canvas board A2 Workbench), oldest first, each with
 * its average score as a bar, its channel and length, and its per-skill scores (1 to 4). Below:
 * the change from the first take to the last, said only as far as the data shows it. "Record take
 * N" stores a typed take and the list polls until it is scored. Spoken takes come from the coach's
 * voice room (CO-6).
 */
import "../coach/coach.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { competencyLabel, formatDate } from "../../labels";
import { ErrorNotice, Loading } from "../../components/ui";
import { PRACTICE_NOTICE, coachKeys, takesApi, useTakes, type TakeOut } from "../coach/api";
import type { Story } from "./api";

/** The mean of a scored take's per-skill scores, 1 to 4. */
export const takeAverage = (t: TakeOut) => {
  const scores = t.scores ?? [];
  return scores.length === 0 ? 0 : scores.reduce((sum, s) => sum + s.score, 0) / scores.length;
};

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s) % 60).padStart(2, "0")}`;

/** "1:52" for a spoken take with a length; null otherwise. */
export const takeDuration = (t: TakeOut) => (t.channel === "voice" && (t.duration_s ?? 0) > 0 ? clock(t.duration_s ?? 0) : null);

/** The scored take with the highest average; the later one on a tie. */
export function bestTake(takes: TakeOut[]): TakeOut | null {
  const scored = takes.filter((t) => t.status === "scored" && (t.scores ?? []).length > 0);
  return scored.reduce<TakeOut | null>((best, t) => (!best || takeAverage(t) >= takeAverage(best) ? t : best), null);
}

/**
 * The first-to-last change, oldest first. "Shorter and stronger each time" only when every take
 * beat the one before it; otherwise the first and last compared.
 */
export function takesTrend(oldestFirst: TakeOut[]): string | null {
  const scored = oldestFirst.filter((t) => t.status === "scored" && (t.scores ?? []).length > 0);
  if (scored.length < 2) return null;
  const first = scored[0];
  const last = scored[scored.length - 1];
  const timed = scored.every((t) => takeDuration(t) !== null);
  const pairs = scored.slice(1).map((t, i) => [scored[i], t] as const);
  const strongerEach = pairs.every(([a, b]) => takeAverage(b) > takeAverage(a));
  const shorterEach = timed && pairs.every(([a, b]) => (b.duration_s ?? 0) < (a.duration_s ?? 0));
  const lengths = timed ? `${takeDuration(first)} → ${takeDuration(last)}. ` : "";
  if (strongerEach && shorterEach) return `${lengths}Shorter and stronger each time.`;
  if (strongerEach) return `${lengths}Stronger each time.`;
  const diff = takeAverage(last) - takeAverage(first);
  if (diff > 0) return `${lengths}Stronger than your first take.`;
  if (diff < 0) return `${lengths}Not as strong as your first take yet. Try the coach notes.`;
  return `${lengths}About as strong as your first take.`;
}

export function StoryTakes({ story }: { story: Story }) {
  const takes = useTakes(story.id);
  const [recording, setRecording] = useState(false);
  const [text, setText] = useState("");
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: () => takesApi.create(story.id, { text: text.trim(), channel: "text" }),
    onSuccess: (take) => {
      queryClient.setQueryData<TakeOut[]>(coachKeys.takes(story.id), (list) => [take, ...(list ?? [])]);
      void queryClient.invalidateQueries({ queryKey: coachKeys.takes(story.id) });
      setText("");
      setRecording(false);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim() && !create.isPending) create.mutate();
  };

  // The API sends the takes newest first; the timeline reads oldest first.
  const list = [...(takes.data ?? [])].reverse();
  const canPractice = story.skills.length > 0;
  const trend = takesTrend(list);

  return (
    <section className="card story-takes" aria-labelledby="story-takes-heading" data-testid="story-takes">
      <div className="story-takes__head">
        <h3 id="story-takes-heading">Takes</h3>
        {canPractice && !recording && (
          <button className="btn btn--rec" type="button" onClick={() => setRecording(true)}>
            <span className="btn__dot" aria-hidden="true" />
            {list.length > 0 ? `Record take ${list.length + 1}` : "Record a take"}
          </button>
        )}
      </div>

      {!canPractice && <p className="muted">Tag the story with at least one skill, and then you can practice it in takes.</p>}
      {recording && (
        <form className="story-take__form stack" onSubmit={submit} aria-label="Record a take">
          <div className="field">
            <label htmlFor="take-text">Tell the story as you would in the interview</label>
            <textarea id="take-text" rows={6} value={text} maxLength={8000} onChange={(e) => setText(e.target.value)} />
          </div>
          {create.isError && <ErrorNotice error={create.error} title="The take was not saved" />}
          <div className="stories__actions">
            <button className="btn" type="submit" disabled={!text.trim() || create.isPending}>
              {create.isPending ? "Saving" : "Score this take"}
            </button>
            <button className="btn btn--quiet" type="button" onClick={() => setRecording(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {takes.isPending && <Loading label="Loading the takes" />}
      {takes.isError && <ErrorNotice error={takes.error} />}
      {takes.data && list.length === 0 && canPractice && (
        <p className="muted">Each take is one telling of the story, scored on its skills. Spoken takes come from your coach.</p>
      )}
      {list.length > 0 && (
        <ol className="plain-list story-takes__list" aria-label="Takes, oldest first">
          {list.map((t, i) => (
            <Take key={t.id} take={t} number={i + 1} />
          ))}
        </ol>
      )}
      {trend && <p className="small muted">{trend}</p>}
      {list.some((t) => t.status === "scored") && (
        <p className="small muted" data-testid="practice-notice">
          {PRACTICE_NOTICE}
        </p>
      )}
    </section>
  );
}

function channelLabel(take: TakeOut) {
  if (take.channel !== "voice") return "Typed";
  const length = takeDuration(take);
  return length ? `Spoken · ${length}` : "Spoken";
}

function Take({ take, number }: { take: TakeOut; number: number }) {
  const avg = takeAverage(take);
  const scored = take.status === "scored" && (take.scores ?? []).length > 0;
  return (
    <li className="story-take" data-testid="story-take" data-status={take.status}>
      <div className="story-take__row">
        <span className="story-take__name">Take {number}</span>
        <span className="story-take__track" aria-hidden="true">
          {scored && (
            <span className="story-take__fill" data-level={avg >= 3 ? "ok" : "warn"} style={{ width: `${(avg / 4) * 100}%` }} />
          )}
        </span>
        <span className="story-take__avg">{scored ? avg.toFixed(1) : "–"}</span>
      </div>
      <p className="muted small">
        {formatDate(take.created_at)} · {channelLabel(take)}
        {take.status === "scoring" && <span role="status"> · Scoring this take</span>}
      </p>
      {take.status === "failed" && <p className="field-error">{take.reason ?? "Scoring failed."}</p>}
      {scored && (
        <ul className="plain-list story-take__scores" aria-label={`Take ${number} scores`}>
          {(take.scores ?? []).map((s) => (
            <li key={s.competency}>
              {competencyLabel(s.competency)} <b>{s.score} of 4</b>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
