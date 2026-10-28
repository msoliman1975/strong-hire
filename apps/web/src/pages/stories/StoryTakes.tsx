/**
 * The workbench's takes and versions (canvas board A2 Workbench), filled by S31.
 *
 * - CO-7 (UI): the story's takes, newest first, each with its date, channel and per-skill scores
 *   (1 to 4). "Record a take" stores a typed take and the list polls until it is scored. Spoken
 *   takes come from the coach's voice room (CO-6).
 * - CO-8 (UI): the coach's 60-second and full versions, written on request from the candidate's
 *   own words, with a toggle between them. They are not stored.
 * - "Work on it with the coach" opens a coach session on this story.
 */
import "../coach/coach.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { competencyLabel, formatDate } from "../../labels";
import { ErrorNotice, Loading, Meter, Segmented } from "../../components/ui";
import { PRACTICE_NOTICE, coachKeys, takesApi, useTakes, type TakeOut } from "../coach/api";
import { newCoachPath } from "../coach/paths";
import { filledParts, type Story } from "./api";

export function StoryTakes({ story }: { story: Story }) {
  return (
    <>
      <section className="card" aria-labelledby="story-takes-heading" data-testid="story-takes">
        <div className="story-takes__head">
          <h2 id="story-takes-heading">Takes</h2>
          <Link className="btn btn--secondary" to={newCoachPath({ story: story.id })}>
            Work on it with the coach
          </Link>
        </div>
        <Takes story={story} />
      </section>
      <Versions story={story} />
    </>
  );
}

function Takes({ story }: { story: Story }) {
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

  const list = takes.data ?? [];
  const canPractice = story.skills.length > 0;

  return (
    <div className="stack">
      {!canPractice ? (
        <p className="muted">Tag the story with at least one skill, and then you can practice it in takes.</p>
      ) : recording ? (
        <form className="story-take__form stack" onSubmit={submit} aria-label="Record a take">
          <div className="field">
            <label htmlFor="take-text">Tell the story as you would in the interview</label>
            <textarea
              id="take-text"
              rows={6}
              value={text}
              maxLength={8000}
              onChange={(e) => setText(e.target.value)}
            />
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
      ) : (
        <div>
          <button className="btn" type="button" onClick={() => setRecording(true)}>
            {list.length > 0 ? `Record take ${list.length + 1}` : "Record a take"}
          </button>
        </div>
      )}

      {takes.isPending && <Loading label="Loading the takes" />}
      {takes.isError && <ErrorNotice error={takes.error} />}
      {takes.data && list.length === 0 && (
        <p className="muted">Each take is one telling of the story, scored on its skills.</p>
      )}
      {list.length > 0 && (
        <ol className="plain-list story-takes__list" aria-label="Takes, newest first">
          {list.map((t, i) => (
            <Take key={t.id} take={t} number={list.length - i} />
          ))}
        </ol>
      )}
      {list.some((t) => t.status === "scored") && (
        <p className="small muted" data-testid="practice-notice">
          {PRACTICE_NOTICE}
        </p>
      )}
    </div>
  );
}

function channelLabel(take: TakeOut) {
  if (take.channel !== "voice") return "Typed";
  const s = Math.round(take.duration_s ?? 0);
  return s > 0 ? `Spoken · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "Spoken";
}

function Take({ take, number }: { take: TakeOut; number: number }) {
  return (
    <li className="story-take" data-testid="story-take" data-status={take.status}>
      <p>
        <strong>Take {number}</strong>{" "}
        <span className="muted small">
          {formatDate(take.created_at)} · {channelLabel(take)}
        </span>
      </p>
      {take.status === "scoring" && (
        <p className="muted small" role="status">
          Scoring this take
        </p>
      )}
      {take.status === "failed" && <p className="field-error">{take.reason ?? "Scoring failed."}</p>}
      {take.status === "scored" && (
        <ul className="plain-list story-take__scores" aria-label={`Take ${number} scores`}>
          {(take.scores ?? []).map((s) => (
            <li key={s.competency}>
              <Meter score={s.score} label={competencyLabel(s.competency)} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

type Length = "sixty_second" | "full";

function Versions({ story }: { story: Story }) {
  const [length, setLength] = useState<Length>("sixty_second");
  const write = useMutation({ mutationFn: () => takesApi.versions(story.id) });
  const takes = useTakes(story.id);
  const hasWords = filledParts(story).length > 0 || (takes.data?.length ?? 0) > 0;

  return (
    <section className="card" aria-labelledby="story-versions-heading" data-testid="story-versions">
      <div className="story-takes__head">
        <h2 id="story-versions-heading">Versions</h2>
        <button
          className="btn btn--secondary"
          type="button"
          disabled={!hasWords || write.isPending}
          onClick={() => write.mutate()}
        >
          {write.isPending ? "Writing" : write.data ? "Write them again" : "Write the versions"}
        </button>
      </div>
      {!hasWords && <p className="muted">Fill in a part or record a take, and the coach can write the versions.</p>}
      {hasWords && !write.data && !write.isPending && (
        <p className="muted">A 60-second and a full version, written only from your own words.</p>
      )}
      {write.isPending && <Loading label="The coach is writing the versions" />}
      {write.isError && <ErrorNotice error={write.error} title="The versions were not written" />}
      {write.data && (
        <div>
          <Segmented<Length>
            label="Story length"
            options={[
              { value: "sixty_second", label: "60-second version" },
              { value: "full", label: "Full version" },
            ]}
            value={length}
            onChange={setLength}
          />
          <p className="story-versions__text" data-testid="story-version-text">
            {write.data[length].text}
          </p>
        </div>
      )}
    </section>
  );
}
