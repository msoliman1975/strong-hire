/**
 * ST-14 (mockup #story): one story. Title, status chip and the Draft → Ready → Proven steps (ST-8),
 * the skills it proves, Practice a take (CO-7) and Review with Strova (ST-11), the open
 * suggestions for it (U08, place `story`), the parts with the 60-second and full versions (CO-8),
 * Used for (the "For {company}" tailoring notes, SG-5) and Where it came from, then the takes and
 * the coach notes (ST-6). Edit story opens the part-by-part editor (ST-3).
 */
import "../../components/ux/ux.css";
import "./stories.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { suggestionKeys, suggestionsApi, useSuggestions } from "../../api/suggestions";
import type { Suggestion } from "../../api/types";
import { ErrorNotice, Loading, STORY_PART_LABEL } from "../../components/ui";
import { competencyLabel } from "../../labels";
import { useTakes } from "../coach/api";
import { displayStatusLabel, storiesApi, storyKeys, useStory, type DisplayStatus, type Story } from "./api";
import { reviewPath, storiesPath } from "./paths";
import { StoryEditor } from "./StoryEditor";
import { bestTake, StoryTakes, takeAverage } from "./StoryTakes";
import { CoachNotes, StoryRead } from "./StoryView";

const STEPS: DisplayStatus[] = ["draft", "ready", "proven"];
const CHIP: Record<DisplayStatus, string> = { proven: "ok", ready: "v", draft: "" };

/** SG-5: the tailoring notes ("For {company}: …") accepted on this story. */
export const usedForNotes = (story: Story) => story.notes.filter((n) => /^For [^:]+: /.test(n.text));

/** ST-14: the story's name, renamed in place: Rename turns it into a field; Enter saves, Escape cancels. */
export function StoryTitle({ story }: { story: Story }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const rename = useMutation({
    mutationFn: (title: string) => storiesApi.update(story.id, { title }),
    onSuccess: (saved) => {
      client.setQueryData(storyKeys.one(story.id), saved);
      void client.invalidateQueries({ queryKey: storyKeys.all });
      setDraft(null);
    },
  });
  if (draft === null) {
    return (
      <>
        <h1>{story.title}</h1>
        <button type="button" className="sx-btn quiet sm" onClick={() => setDraft(story.title)}>
          Rename
        </button>
      </>
    );
  }
  const name = draft.trim();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!name) return;
    if (name === story.title) setDraft(null);
    else rename.mutate(name);
  };
  return (
    <form className="sx-row story-page__rename" onSubmit={submit} aria-label="Rename the story">
      <label className="visually-hidden" htmlFor="story-rename">
        Story name
      </label>
      <input
        id="story-rename"
        value={draft}
        maxLength={200}
        autoFocus
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setDraft(null);
        }}
      />
      <button type="submit" className="sx-btn sm" disabled={!name || rename.isPending}>
        Save
      </button>
      <button type="button" className="sx-btn quiet sm" onClick={() => setDraft(null)}>
        Cancel
      </button>
      {rename.isError && <ErrorNotice error={rename.error} title="The name was not saved" />}
    </form>
  );
}

export function StoryPage() {
  const { storyId = "" } = useParams();
  const story = useStory(storyId);
  const [editing, setEditing] = useState(false);
  if (story.isPending) return <Loading label="Loading the story" />;
  if (story.isError) return <ErrorNotice error={story.error} />;
  const s = story.data;
  return (
    <div className="sx-page story-page">
      <Link to={storiesPath} className="sx-small">
        All stories
      </Link>
      <div className="sx-between">
        <div className="sx-stack story-page__head">
          <div className="sx-row">
            <StoryTitle story={s} />
            <span className={`sx-chip ${CHIP[s.display_status]}`} data-testid="story-status">
              {displayStatusLabel[s.display_status]}
            </span>
          </div>
          <div className="sx-row sx-small sx-muted">
            <ol className="story-page__steps" aria-label="Status steps">
              {STEPS.map((step) => (
                <li
                  key={step}
                  className={`sx-chip ${step === s.display_status ? CHIP[step] : ""}`}
                  aria-current={step === s.display_status ? "step" : undefined}
                >
                  {displayStatusLabel[step]}
                </li>
              ))}
            </ol>
            <span>
              {s.skills.length > 0 ? `· proves ${s.skills.map(competencyLabel).join(", ")}` : "· no skill tags yet"}
            </span>
          </div>
        </div>
        <div className="sx-row">
          <a className="sx-btn" href="#story-takes">
            Practice a take
          </a>
          <Link className="sx-btn ghost" to={reviewPath(s.id)}>
            Review with Strova
          </Link>
        </div>
      </div>

      <StorySuggestions story={s} />

      <div className="sx-grid2 story-page__grid">
        <section className="sx-card story-page__parts" aria-label="Story parts">
          {editing ? (
            <StoryEditor story={s} onDone={() => setEditing(false)} />
          ) : (
            <>
              <StoryRead story={s} />
              <div>
                <button type="button" className="sx-btn ghost sm" onClick={() => setEditing(true)}>
                  Edit story
                </button>
              </div>
            </>
          )}
        </section>
        <div className="sx-stack story-page__side">
          <UsedFor story={s} />
          <CameFrom story={s} />
        </div>
      </div>
      <div className="sx-grid2 story-page__grid" id="story-takes">
        <StoryTakes story={s} />
        <CoachNotes story={s} />
      </div>
    </div>
  );
}

function UsedFor({ story }: { story: Story }) {
  const notes = usedForNotes(story);
  return (
    <section className="sx-card" aria-labelledby="used-for-heading">
      <h3 id="used-for-heading">Used for</h3>
      {notes.length === 0 ? (
        <span className="sx-small sx-muted">Not used by a role yet.</span>
      ) : (
        notes.map((n) => (
          <span key={n.at} className="sx-notice t sx-small">
            {n.text}
          </span>
        ))
      )}
    </section>
  );
}

function CameFrom({ story }: { story: Story }) {
  const takes = useTakes(story.id);
  const best = bestTake(takes.data ?? []);
  const count = takes.data?.length ?? 0;
  return (
    <section className="sx-card" aria-labelledby="came-from-heading">
      <h3 id="came-from-heading">Where it came from</h3>
      <span className="sx-small" data-testid="story-source">
        {story.source === "debrief_answer" ? (
          <>
            A debrief answer
            {story.source_session_id && (
              <>
                {" · "}
                <Link to={`/sessions/${story.source_session_id}/debrief`}>Open the debrief</Link>
              </>
            )}
          </>
        ) : story.source === "coach" ? (
          "Crafted with Strova, from your own words"
        ) : (
          "Written by you"
        )}
      </span>
      <span className="sx-small sx-muted">
        {count === 0
          ? "No takes yet"
          : `${count} ${count === 1 ? "take" : "takes"}${best ? ` · best ${takeAverage(best).toFixed(1)} of 4` : ""}`}
      </span>
    </section>
  );
}

/** U08 on the story page: tune (Apply, then Undo) and tailoring notes for this story. */
function StorySuggestions({ story }: { story: Story }) {
  const list = useSuggestions("story", { story_id: story.id });
  const open = (list.data ?? []).filter((s) => s.kind !== "review");
  if (open.length === 0) return null;
  return (
    <div className="sx-stack" aria-label="Strova suggests" role="region">
      {open.map((s) => (
        <StorySuggestion key={s.id} suggestion={s} storyId={story.id} />
      ))}
    </div>
  );
}

function StorySuggestion({ suggestion, storyId }: { suggestion: Suggestion; storyId: string }) {
  const client = useQueryClient();
  const [applied, setApplied] = useState(false);
  const refresh = () => {
    void client.invalidateQueries({ queryKey: storyKeys.all });
    void client.invalidateQueries({ queryKey: suggestionKeys.place("story", storyId) });
  };
  const accept = useMutation({
    mutationFn: () => suggestionsApi.accept(suggestion.id),
    onSuccess: () => {
      setApplied(true);
      void client.invalidateQueries({ queryKey: storyKeys.all });
    },
  });
  const dismiss = useMutation({ mutationFn: () => suggestionsApi.dismiss(suggestion.id), onSuccess: refresh });
  const undo = useMutation({
    mutationFn: () => suggestionsApi.undo(suggestion.id),
    onSuccess: () => {
      setApplied(false);
      void client.invalidateQueries({ queryKey: storyKeys.all });
    },
  });
  const busy = accept.isPending || dismiss.isPending || undo.isPending;
  const error = accept.error ?? dismiss.error ?? undo.error;
  const p = suggestion.payload;
  if (applied) {
    return (
      <div className="sx-notice ok" role="status">
        <strong>{p.kind === "tailor_role" ? `Note added for ${p.company}.` : "Applied to this story."}</strong>{" "}
        <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => undo.mutate()}>
          Undo
        </button>
      </div>
    );
  }
  if (p.kind !== "tune_story" && p.kind !== "tailor_role") return null;
  return (
    <div className="sx-card tight coach" role="group" aria-label={p.kind === "tune_story" ? "Tune this story" : `Tailor for ${p.company}`}>
      <span className={`sx-eyebrow ${p.kind === "tailor_role" ? "teal" : ""}`}>
        {p.kind === "tune_story" ? `Strova suggests · ${STORY_PART_LABEL[p.edit.part]}` : `Tailor for ${p.company}`}
      </span>
      <span>{p.kind === "tune_story" ? suggestion.reason : p.note}</span>
      {p.kind === "tune_story" && (
        <div className="sx-diff">
          {p.edit.before && (
            <>
              <del>{p.edit.before}</del>
              <br />
            </>
          )}
          <ins>{p.edit.after}</ins>
        </div>
      )}
      {error && (
        <span className="sx-small" role="alert">
          {error.message}
        </span>
      )}
      <div className="sx-row">
        <button type="button" className="sx-btn sm" disabled={busy} onClick={() => accept.mutate()}>
          {p.kind === "tune_story" ? "Apply" : "Add to story"}
        </button>
        <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => dismiss.mutate()}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
