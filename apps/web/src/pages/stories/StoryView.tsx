/**
 * The selected story in the studio (canvas board A2 Workbench, right pane). It opens as a read
 * view; "Edit story" is one click away (StoryEditor).
 *
 * - ST-3: the five parts as readable text, the status, the skills it proves, and the fix notes
 *   from debriefs, numbered, newest first.
 * - CO-8: the length toggle: the parts, or the coach's 60-second and full versions, written on
 *   request from the candidate's own words. They are not stored.
 * - CO-7: the takes timeline (StoryTakes).
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { competencyLabel, formatDate } from "../../labels";
import { EXPLAIN, Explain } from "../../components/Explain";
import { CoachMark, ErrorNotice, Loading, Segmented, STORY_PART_LABEL } from "../../components/ui";
import { takesApi, useTakes } from "../coach/api";
import { newCoachPath } from "../coach/paths";
import { filledParts, STORY_PARTS, useStory, type Story } from "./api";
import { StoryEditor } from "./StoryEditor";
import { StoryStatusBadge } from "./StoriesPage";
import { bestTake, StoryTakes, takeAverage, takeDuration } from "./StoryTakes";

type Length = "parts" | "sixty_second" | "full";

export function StoryView({ storyId }: { storyId: string }) {
  const story = useStory(storyId);
  const [editing, setEditing] = useState(false);
  if (story.isPending) return <Loading label="Loading the story" />;
  if (story.isError) return <ErrorNotice error={story.error} />;
  const s = story.data;
  return (
    <div className="studio__detail">
      <article className="card story-view" aria-labelledby="story-title-heading">
        <StoryHead story={s} editing={editing} onEdit={() => setEditing(true)} />
        {editing ? <StoryEditor story={s} onDone={() => setEditing(false)} /> : <StoryRead story={s} />}
      </article>
      <aside className="studio__aside" aria-label="Takes and coach notes">
        <StoryTakes story={s} />
        <CoachNotes story={s} />
      </aside>
    </div>
  );
}

function StoryHead({ story, editing, onEdit }: { story: Story; editing: boolean; onEdit: () => void }) {
  const takes = useTakes(story.id);
  const best = bestTake(takes.data ?? []);
  const skills = story.skills.map(competencyLabel);
  return (
    <header className="story-view__head">
      <div className="story-view__title">
        <h2 id="story-title-heading">{story.title}</h2>
        <span className="story-view__status">
          <StoryStatusBadge status={story.display_status} />
          <Explain topic="Proven">{EXPLAIN.proven}</Explain>
          {best && <span className="story-view__score">Best take {takeAverage(best).toFixed(1)} of 4</span>}
        </span>
      </div>
      <p className="muted">
        {skills.length > 0 ? (
          <>
            Proves{" "}
            {skills.map((k, i) => (
              <span key={k}>
                {i > 0 && (i === skills.length - 1 ? " and " : ", ")}
                <b>{k}</b>
              </span>
            ))}
          </>
        ) : (
          "No skill tags yet"
        )}
        {best && takeDuration(best) && <> · Best take {takeDuration(best)}</>}
      </p>
      <p className="muted small">
        {story.status === "proven"
          ? "Proven in a Realistic rehearsal."
          : "Becomes Proven when a Realistic answer that uses it meets the bar."}
      </p>
      {!editing && (
        <div className="stories__actions">
          <button className="btn btn--secondary" type="button" onClick={onEdit}>
            Edit story
          </button>
          <Link className="btn btn--quiet" to={newCoachPath({ story: story.id })}>
            Work on it with the coach
          </Link>
        </div>
      )}
    </header>
  );
}

export function StoryRead({ story }: { story: Story }) {
  const [length, setLength] = useState<Length>("parts");
  const write = useMutation({ mutationFn: () => takesApi.versions(story.id) });
  const takes = useTakes(story.id);
  const hasWords = filledParts(story).length > 0 || (takes.data?.length ?? 0) > 0;

  const choose = (next: Length) => {
    setLength(next);
    if (next !== "parts" && !write.data && !write.isPending && hasWords) write.mutate();
  };

  return (
    <div className="stack" data-testid="story-versions">
      <Segmented<Length>
        label="Story length"
        options={[
          { value: "parts", label: "Story parts" },
          { value: "sixty_second", label: "60-second version" },
          { value: "full", label: "Full version" },
        ]}
        value={length}
        onChange={choose}
      />
      {length === "parts" ? (
        <ol className="plain-list story-view__parts">
          {STORY_PARTS.map((p) => (
            <li key={p} data-part={p}>
              <span className="story-view__part-label">{STORY_PART_LABEL[p]}</span>
              {story[p]?.trim() ? (
                <p>{story[p]}</p>
              ) : (
                <p className="muted">
                  <i>Empty.</i>{" "}
                  <Link className="text-link" to={newCoachPath({ story: story.id })}>
                    Add it with the coach
                  </Link>
                </p>
              )}
            </li>
          ))}
        </ol>
      ) : !hasWords ? (
        <p className="muted">Fill in a part or record a take, and the coach can write the versions.</p>
      ) : write.isPending ? (
        <Loading label="The coach is writing the versions" />
      ) : write.isError ? (
        <ErrorNotice error={write.error} title="The versions were not written" />
      ) : (
        write.data && (
          <>
            <p className="story-versions__text" data-testid="story-version-text">
              {write.data[length].text}
            </p>
            <p className="muted small">
              Written by your coach from your own words. Not saved.{" "}
              <button className="text-button" type="button" onClick={() => write.mutate()}>
                Write them again
              </button>
            </p>
          </>
        )
      )}
    </div>
  );
}

/** The fix notes from debriefs, numbered, newest first (ST-6 sends them here). */
export function CoachNotes({ story }: { story: Story }) {
  const notes = [...story.notes].sort((a, b) => b.at.localeCompare(a.at));
  return (
    <section className="card card--dark story-notes" aria-labelledby="story-notes-heading">
      <h3 id="story-notes-heading">
        <CoachMark size={20} tone="dark" />
        Coach notes
      </h3>
      {notes.length === 0 ? (
        <p className="story-notes__empty">When a debrief answer uses this story, its fix shows here.</p>
      ) : (
        <ol className="plain-list story-notes__list" aria-label="Fix notes, newest first">
          {notes.map((n, i) => (
            <li key={`${n.at}-${i}`} data-testid="story-note">
              <span className="story-notes__n" aria-hidden="true">
                {i + 1}
              </span>
              <div>
                <p>{n.text}</p>
                <p className="small story-notes__meta">
                  {formatDate(n.at)}
                  {n.session_id && (
                    <>
                      {" · "}
                      <Link to={`/sessions/${n.session_id}/debrief`}>Open the debrief</Link>
                    </>
                  )}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
