/**
 * ST-3: the story workbench (canvas board A2 Workbench). The candidate edits the title, the five
 * parts and the skill tags, and reads the fix notes from debriefs, newest first. Save sends only
 * the fields that changed. The status is shown, never edited (ST-7).
 */
import "./stories.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { formatDate } from "../../labels";
import { ErrorNotice, Loading, PageHead, STORY_PART_LABEL, StoryPartChip } from "../../components/ui";
import { STORY_PARTS, storiesApi, storyKeys, useStory, type Competency, type Story, type StoryPatch } from "./api";
import { storiesPath } from "./paths";
import { SkillPicker } from "./SkillPicker";
import { StoryStatusBadge } from "./StoriesPage";
import { StoryTakes } from "./StoryTakes";

type Part = (typeof STORY_PARTS)[number];

const PART_HINT: Record<Part, string> = {
  context: "Where you were and what was going on.",
  stakes: "What could go wrong, and why it mattered.",
  action: "What you did yourself. Say “I”, not “we”.",
  result: "What changed, with a number if you have one.",
  reflection: "What you learned, or what you would do differently.",
};

export function StoryWorkbenchPage() {
  const { storyId = "" } = useParams();
  const story = useStory(storyId);
  return (
    <div className="stories stack">
      <p>
        <Link className="text-link" to={storiesPath}>
          All stories
        </Link>
      </p>
      {story.isPending && <Loading label="Loading the story" />}
      {story.isError && <ErrorNotice error={story.error} />}
      {story.data && <Workbench key={story.data.id} story={story.data} />}
    </div>
  );
}

type Draft = { title: string; skills: Competency[] } & Record<Part, string>;

function draftOf(s: Story): Draft {
  return {
    title: s.title,
    skills: [...s.skills],
    context: s.context ?? "",
    stakes: s.stakes ?? "",
    action: s.action ?? "",
    result: s.result ?? "",
    reflection: s.reflection ?? "",
  };
}

/** The fields that changed, as the PATCH body. */
function changes(before: Draft, after: Draft): StoryPatch {
  const patch: StoryPatch = {};
  if (after.title.trim() !== before.title) patch.title = after.title.trim();
  for (const p of STORY_PARTS) {
    if (after[p].trim() !== before[p].trim()) patch[p] = after[p].trim() === "" ? null : after[p];
  }
  const sameSkills =
    after.skills.length === before.skills.length && after.skills.every((c) => before.skills.includes(c));
  if (!sameSkills) patch.skills = after.skills;
  return patch;
}

function Workbench({ story }: { story: Story }) {
  const initial = draftOf(story);
  const [draft, setDraft] = useState<Draft>(initial);
  const [titleMissing, setTitleMissing] = useState(false);
  const [saved, setSaved] = useState(false);
  const queryClient = useQueryClient();
  const patch = changes(initial, draft);
  const dirty = Object.keys(patch).length > 0;

  const save = useMutation({
    mutationFn: () => storiesApi.update(story.id, patch),
    onSuccess: (next) => {
      queryClient.setQueryData(storyKeys.one(story.id), next);
      void queryClient.invalidateQueries({ queryKey: storyKeys.all });
      setSaved(true);
    },
  });

  const edit = (changesToDraft: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...changesToDraft }));
    setSaved(false);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (draft.title.trim() === "") {
      setTitleMissing(true);
      return;
    }
    if (dirty) save.mutate();
  };

  const notes = [...story.notes].sort((a, b) => b.at.localeCompare(a.at));

  return (
    <>
      <PageHead title={story.title} eyebrow="A · Story workbench">
        <p className="story-head__meta">
          <StoryStatusBadge status={story.status} />
          <span className="muted small">
            {story.status === "proven"
              ? "Proven in a Realistic rehearsal."
              : "Becomes Proven when a Realistic answer that uses it meets the bar."}
          </span>
        </p>
      </PageHead>

      <div className="workbench">
        <form className="card workbench__main stack" onSubmit={submit} noValidate aria-label="Edit story">
          <div className="field">
            <label htmlFor="story-title">Title</label>
            <input
              id="story-title"
              type="text"
              value={draft.title}
              maxLength={200}
              aria-invalid={titleMissing || undefined}
              onChange={(e) => {
                edit({ title: e.target.value });
                setTitleMissing(false);
              }}
            />
            {titleMissing && (
              <p className="field-error" role="alert">
                A story needs a title.
              </p>
            )}
          </div>

          <ol className="plain-list workbench__parts">
            {STORY_PARTS.map((p) => (
              <li key={p} className="workbench__part" data-part={p}>
                <label htmlFor={`story-${p}`} className="workbench__part-label">
                  <StoryPartChip part={p} />
                </label>
                <p className="hint muted small" id={`story-${p}-hint`}>
                  {PART_HINT[p]}
                </p>
                <textarea
                  id={`story-${p}`}
                  rows={p === "action" ? 5 : 3}
                  value={draft[p]}
                  aria-describedby={`story-${p}-hint`}
                  placeholder={`${STORY_PART_LABEL[p]}: not written yet`}
                  onChange={(e) => edit({ [p]: e.target.value })}
                />
              </li>
            ))}
          </ol>

          <SkillPicker value={draft.skills} onChange={(skills) => edit({ skills })} />

          {save.isError && <ErrorNotice error={save.error} title="The story was not saved" />}
          <div className="stories__actions">
            <button className="btn" type="submit" disabled={!dirty || save.isPending}>
              {save.isPending ? "Saving" : "Save changes"}
            </button>
            {dirty && (
              <button className="btn btn--quiet" type="button" onClick={() => setDraft(initial)}>
                Undo changes
              </button>
            )}
            <span role="status" className="muted small">
              {saved && !dirty ? "Saved" : ""}
            </span>
          </div>
        </form>

        <aside className="workbench__side stack" aria-label="Notes, takes and versions">
          <section className="card" aria-labelledby="story-notes-heading">
            <h2 id="story-notes-heading">Fix notes</h2>
            {notes.length === 0 ? (
              <p className="muted">When a debrief answer uses this story, its fix shows here.</p>
            ) : (
              <ol className="plain-list workbench__notes" aria-label="Fix notes, newest first">
                {notes.map((n, i) => (
                  <li key={`${n.at}-${i}`} data-testid="story-note">
                    <p>{n.text}</p>
                    <p className="muted small">
                      {formatDate(n.at)}
                      {n.session_id && (
                        <>
                          {" · "}
                          <Link className="text-link" to={`/sessions/${n.session_id}/debrief`}>
                            Open the debrief
                          </Link>
                        </>
                      )}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </section>
          <StoryTakes story={story} />
        </aside>
      </div>
    </>
  );
}
