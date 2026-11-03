/**
 * ST-11 (mockup #review): Review with Strova. The story's parts on the left; on the right, the
 * ask panel, then Strova's review: a summary, a before-and-after edit per part to Accept or Skip
 * (the edits use the user's own words, U08), and the missing parts with "Answer with Strova",
 * which continues crafting on this story at the first missing part.
 *
 * ST-11 (A, B): the panel says plainly when Strova has finished, counts the notes done, and says so
 * when every note is done. Each note has Edit, which opens that part (or, on a styled story, its
 * section's slots) in place with Strova's note as guidance, and Skip.
 *
 * POST /stories/{id}/review queues the review; it arrives as the story's open `review`
 * suggestion, which this page polls for.
 *
 * A styled story (SC-1) shows its sections; its review is notes only, named by section (review
 * v2), and each section is improved with Strova on the story page (SC-11).
 */
import "../../components/ux/ux.css";
import "./stories.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import { suggestionsApi } from "../../api/suggestions";
import type { Suggestion } from "../../api/types";
import { markdownKeys, MarkdownToolbar } from "../../components/markdown/markdown";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading, STORY_PART_LABEL } from "../../components/ui";
import { newCoachPath } from "../coach/paths";
import { SECTION_LABEL, type StorySection } from "../coach/outline";
import { STORY_PARTS, storiesApi, storyKeys, useStory, type Story } from "./api";
import { EditableSection, OutlineStory } from "./OutlineStory";
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
        <section className="sx-card" aria-label={s.outline ? "Story sections" : "Story parts"}>
          {s.outline ? (
            <OutlineStory story={s} outline={s.outline} readOnly />
          ) : (
          STORY_PARTS.map((p) => (
            <div key={p} className="sx-part" data-testid={`part-${p}`}>
              <span className="part-lbl" data-part={p}>
                {s[p]?.trim() ? "●" : "○"} {STORY_PART_LABEL[p]}
              </span>
              {s[p]?.trim() ? <span>{s[p]}</span> : <span className="sx-muted">Not written yet</span>}
            </div>
          ))
          )}
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
                <h2 className="review-heading">Ask Strova to review</h2>
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

type Part = (typeof STORY_PARTS)[number];

/** Review v2 names a styled story's notes by part; the section the part belongs to. */
function partSectionKey(story: Story, part: Part): StorySection {
  const opening: StorySection = story.outline?.style === "carl" ? "challenge" : "situation";
  const by: Record<Part, StorySection> = {
    context: opening,
    stakes: opening,
    action: "action",
    result: "result",
    reflection: "learning",
  };
  return by[part];
}

/** Review v2 names a styled story's notes by part; show the section the part belongs to. */
function partSection(story: Story, part: Part): string {
  if (part === "stakes" && story.outline?.style !== "carl") {
    return `${SECTION_LABEL.situation} and ${SECTION_LABEL.task}`;
  }
  return SECTION_LABEL[partSectionKey(story, part)];
}

type Done = "applied" | "edited" | "skipped";
const DONE_TEXT: Record<Done, string> = { applied: "updated", edited: "edited", skipped: "skipped" };

/** ST-11 (Edit): the part (classic) or its section (styled), opened in place with Strova's note as
 * guidance. A suggested edit can be used as the starting text. */
function NoteEditor({
  story,
  note,
  label,
  onDone,
  onCancel,
}: {
  story: Story;
  note: Review["notes"][number];
  label: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const client = useQueryClient();
  const [text, setText] = useState(story[note.part] ?? "");
  const area = useRef<HTMLTextAreaElement>(null);
  const keys = markdownKeys(setText);
  const save = useMutation({
    mutationFn: () => storiesApi.update(story.id, { [note.part]: text.trim() || null }),
    onSuccess: (saved) => {
      client.setQueryData(storyKeys.one(story.id), saved);
      void client.invalidateQueries({ queryKey: storyKeys.all });
      onDone();
    },
  });
  const guidance = (
    <div className="sx-notice v sx-small review-guidance" data-testid="review-guidance">
      <strong>Strova's note:</strong> {note.note}
      {note.edit && (
        <>
          <br />
          <strong>Her suggestion, from your words:</strong> {note.edit.after}
        </>
      )}
    </div>
  );
  if (story.outline) {
    const section = story.outline.sections.find((s) => s.section === partSectionKey(story, note.part));
    return (
      <div className="sx-card tight review-editor" role="group" aria-label={`Edit ${label}`}>
        {guidance}
        {section && <EditableSection story={story} outline={story.outline} section={section} />}
        <div className="sx-row">
          <button type="button" className="sx-btn sm" onClick={onDone}>
            Done with {label}
          </button>
          <button type="button" className="sx-btn quiet sm" onClick={onCancel}>
            Close
          </button>
        </div>
      </div>
    );
  }
  const id = `review-edit-${note.part}`;
  return (
    <form
      className="sx-card tight review-editor"
      aria-label={`Edit ${label}`}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {guidance}
      <label htmlFor={id} className="review-editor__label">
        {label}
      </label>
      <MarkdownToolbar target={area} onChange={setText} label={`Format ${label}`} />
      <textarea
        id={id}
        ref={area}
        rows={4}
        maxLength={8000}
        value={text}
        autoFocus
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (keys.onKeyDown(e)) return;
          if (e.key === "Escape") onCancel();
        }}
        onPaste={keys.onPaste}
      />
      {save.isError && <ErrorNotice error={save.error} title={`${label} was not saved`} />}
      <div className="sx-row">
        <button type="submit" className="sx-btn sm" disabled={save.isPending}>
          Save {label}
        </button>
        {note.edit && (
          <button type="button" className="sx-btn ghost sm" onClick={() => setText(note.edit?.after ?? text)}>
            Start from her suggestion
          </button>
        )}
        <button type="button" className="sx-btn quiet sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ReviewResult({ suggestion, review, story }: { suggestion: Suggestion; review: Review; story: Story }) {
  const client = useQueryClient();
  const [done, setDone] = useState<Partial<Record<Part, Done>>>({});
  const [editing, setEditing] = useState<Part | null>(null);
  const mark = (part: Part, how: Done) => {
    setDone((d) => ({ ...d, [part]: how }));
    setEditing(null);
  };
  const accept = useMutation({
    mutationFn: (part: Part) => suggestionsApi.accept(suggestion.id, { parts: [part] }),
    onSuccess: (_out, part) => {
      mark(part, "applied");
      void client.invalidateQueries({ queryKey: storyKeys.all });
    },
  });
  const notes = review.notes;
  const handled = notes.filter((n) => done[n.part]).length;
  const withEdits = notes.filter((n) => n.edit).length;
  const allDone = notes.length > 0 && handled === notes.length;
  const firstMissing = STORY_PARTS.find((p) => !story[p]?.trim());

  useEffect(() => {
    document.title = `Strova's review is ready | Strong Hire`;
  }, []);

  return (
    <>
      <div className="sx-row">
        <Strova mode={allDone ? "celebrating" : "analysing"} size={72} />
        <h2 className="review-heading">Strova's review</h2>
      </div>
      {/* ST-11 (A): say plainly that the review is finished, and announce it. */}
      <p className="sx-notice ok sx-small review-done" role="status" data-testid="review-done">
        <strong>Strova has finished reviewing your story.</strong>{" "}
        {notes.length === 0
          ? "She has no notes: it reads well as it is."
          : `${notes.length} ${notes.length === 1 ? "note" : "notes"}${withEdits ? `, ${withEdits} with a suggested edit` : ""}.`}
      </p>
      <div className="sx-notice ok sx-small">{review.summary}</div>
      {notes.length > 0 && (
        <p className="sx-small sx-muted" data-testid="review-progress">
          {allDone ? "Every note done." : `${handled} of ${notes.length} notes done.`}
        </p>
      )}
      {accept.isError && <ErrorNotice error={accept.error} />}
      {notes.map((n) => {
        const label = story.outline ? partSection(story, n.part) : STORY_PART_LABEL[n.part];
        const how = done[n.part];
        if (how) {
          return (
            <div key={n.part} className="sx-notice ok sx-small" role="status">
              <strong>
                {label} {DONE_TEXT[how]}.
              </strong>
            </div>
          );
        }
        if (editing === n.part) {
          return (
            <NoteEditor
              key={n.part}
              story={story}
              note={n}
              label={label}
              onDone={() => mark(n.part, "edited")}
              onCancel={() => setEditing(null)}
            />
          );
        }
        const empty = !story[n.part]?.trim() && !story.outline;
        // A styled story's parts are rendered from its outline: an edit is made in its section.
        const canAccept = !!n.edit && !story.outline;
        return (
          <div
            key={n.part}
            className={canAccept ? "sx-card tight" : `sx-notice ${empty ? "warn" : "v"} sx-small review-note`}
            role="group"
            aria-label={canAccept ? `Edit to ${label}` : `Note on ${label}`}
            data-testid={`note-${n.part}`}
          >
            {canAccept ? <span className="sx-eyebrow">{label}</span> : <strong>{empty ? `${label} is missing.` : label}</strong>}{" "}
            <span className="sx-small">{n.note}</span>
            {canAccept && n.edit && (
              <div className="sx-diff">
                {n.edit.before && (
                  <>
                    <del>{n.edit.before}</del>
                    <br />
                  </>
                )}
                <ins>{n.edit.after}</ins>
              </div>
            )}
            <div className="sx-row">
              {canAccept && (
                <button type="button" className="sx-btn sm" disabled={accept.isPending} onClick={() => accept.mutate(n.part)}>
                  Accept
                </button>
              )}
              {/* ST-11 (B): open the part, or its section, with the note as guidance. */}
              <button type="button" className={canAccept ? "sx-btn ghost sm" : "sx-btn sm"} onClick={() => setEditing(n.part)}>
                Edit {label}
              </button>
              <button type="button" className="sx-btn quiet sm" onClick={() => mark(n.part, "skipped")}>
                Skip
              </button>
              {empty && firstMissing && (
                <Link to={newCoachPath({ story: story.id })} className="sx-small">
                  Answer with Strova
                </Link>
              )}
            </div>
          </div>
        );
      })}
      {allDone && (
        <div className="sx-notice ok review-all-done" role="status" data-testid="review-all-done">
          <strong>You've worked through every note.</strong> Your story is up to date.{" "}
          <Link to={storyPath(story.id)}>Back to the story</Link>
        </div>
      )}
    </>
  );
}
