/**
 * ST-3: editing a story in the studio, one click from the read view (StoryView). The candidate
 * edits the title, the five parts and the skill tags. Save sends only the fields that changed.
 * The status is shown, never edited (ST-7).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorNotice, STORY_PART_LABEL, StoryPartChip } from "../../components/ui";
import { STORY_PARTS, storiesApi, storyKeys, type Competency, type Story, type StoryPatch } from "./api";
import { SkillPicker } from "./SkillPicker";

type Part = (typeof STORY_PARTS)[number];

const PART_HINT: Record<Part, string> = {
  context: "Where you were and what was going on.",
  stakes: "What could go wrong, and why it mattered.",
  action: "What you did yourself. Say “I”, not “we”.",
  result: "What changed, with a number if you have one.",
  reflection: "What you learned, or what you would do differently.",
};

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

/** The edit form: title, the five parts and the skill tags. Save sends only what changed. */
export function StoryEditor({ story, onDone }: { story: Story; onDone: () => void }) {
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

  return (
    <form className="workbench__main stack" onSubmit={submit} noValidate aria-label="Edit story">
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
        <button className="btn btn--secondary" type="button" onClick={onDone}>
          {dirty ? "Cancel" : "Back to the story"}
        </button>
        <span role="status" className="muted small">
          {saved && !dirty ? "Saved" : ""}
        </span>
      </div>
    </form>
  );
}
