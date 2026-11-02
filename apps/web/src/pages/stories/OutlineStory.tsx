/**
 * The organized story page (SC-10 to SC-13, D-2, D-10, D-11).
 *
 * - OutlineStory: the sections in style order with their slots. Every slot is edited in place
 *   (SC-10); action steps are numbered, added, moved and removed (1 to 5); the metric reads
 *   before → after. Required empty slots are marked; empty optional ones stay quiet.
 * - Improve with Strova per section (SC-11): an optional note, then before-and-after edits to
 *   Accept or Reject, or questions that open a session with Strova on the story.
 * - StyleSwitch (SC-12): Switch to CARL or STAR, with "Rewrite the wording too" as a preview.
 * - OrganizeBanner (SC-13): a classic story's one click into STAR, previewed first.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { Markdown, markdownKeys, MarkdownToolbar } from "../../components/markdown/markdown";
import { Strova } from "../../components/strova";
import { ErrorNotice } from "../../components/ui";
import {
  CONTEXT_SLOTS,
  CORE_SLOTS,
  EMPTY_SLOT,
  isFilled,
  SECTION_LABEL,
  sectionSlots,
  SLOT_LABEL,
  STEP_FIELDS,
  STYLE_NAME,
  type OutlineSlot,
  type SlotView,
  type StoryOutline,
  type StorySection,
} from "../coach/outline";
import { newCoachPath } from "../coach/paths";
import { storiesApi, storyKeys, type SectionImprove, type SlotEdit, type SlotEditIn, type Story } from "./api";

type Section = StoryOutline["sections"][number];
const MAX_STEPS = 5;

function useSaveStory(story: Story) {
  const client = useQueryClient();
  return (saved: Story) => {
    client.setQueryData(storyKeys.one(story.id), saved);
    void client.invalidateQueries({ queryKey: storyKeys.all });
  };
}

const slotName = (v: Pick<SlotView, "key" | "step">) =>
  `${v.step !== null ? `Step ${v.step + 1}: ` : ""}${SLOT_LABEL[v.key] ?? v.key}`;

/** The metric as before → after, when the candidate gave the numbers. */
function MetricLine({ slot }: { slot: OutlineSlot & { before?: string | null; after?: string | null; unit?: string | null } }) {
  if (!slot.before && !slot.after) return null;
  const unit = slot.unit ?? "";
  return (
    <span className="outline-slot__metric" data-testid="metric-line">
      {slot.before ?? "?"}
      {unit} → {slot.after ?? "?"}
      {unit}
    </span>
  );
}

// --- SC-10: one slot, edited in place -----------------------------------------------------------

function SlotRow({
  story,
  view,
  readOnly,
  startEditing,
}: {
  story: Story;
  view: SlotView;
  readOnly?: boolean;
  startEditing?: boolean;
}) {
  const save = useSaveStory(story);
  const [draft, setDraft] = useState<{ text: string; before: string; after: string } | null>(
    startEditing ? { text: view.slot.text ?? "", before: "", after: "" } : null,
  );
  const edit = useMutation({
    mutationFn: (body: SlotEditIn) => storiesApi.editOutline(story.id, { slots: [body] }),
    onSuccess: (saved) => {
      save(saved);
      setDraft(null);
    },
  });
  const area = useRef<HTMLTextAreaElement>(null);
  const setText = (text: string) => setDraft((d) => (d ? { ...d, text } : d));
  const keys = markdownKeys(setText);
  const { slot, key } = view;
  const metric = key === "metric";
  const required = CORE_SLOTS.has(key);
  const filled = isFilled(slot);
  const name = slotName(view);
  const ref = { section: view.section, slot: key, step: view.step };
  const id = `slot-${view.section}-${key}-${view.step ?? "x"}`;

  if (draft !== null) {
    const submit = (e: FormEvent) => {
      e.preventDefault();
      edit.mutate({
        ...ref,
        text: draft.text,
        skipped: false,
        ...(metric ? { before: draft.before || null, after: draft.after || null } : {}),
      });
    };
    return (
      <li className="outline-slot" data-state="editing" data-testid="outline-slot" data-slot={id}>
        <form className="sx-stack outline-slot__form" onSubmit={submit} aria-label={`Edit ${name}`}>
          <label htmlFor={id} className="outline-slot__name">
            {name}
          </label>
          <MarkdownToolbar target={area} onChange={setText} label={`Format ${name}`} />
          <textarea
            id={id}
            ref={area}
            value={draft.text}
            rows={3}
            maxLength={8000}
            autoFocus
            onChange={(e) => setDraft({ ...draft, text: e.target.value })}
            onPaste={keys.onPaste}
            onKeyDown={(e) => {
              if (keys.onKeyDown(e)) return;
              if (e.key === "Escape") setDraft(null);
            }}
          />
          {metric && (
            <div className="sx-row outline-slot__numbers">
              <label>
                Before
                <input value={draft.before} maxLength={100} onChange={(e) => setDraft({ ...draft, before: e.target.value })} />
              </label>
              <label>
                After
                <input value={draft.after} maxLength={100} onChange={(e) => setDraft({ ...draft, after: e.target.value })} />
              </label>
            </div>
          )}
          {edit.isError && <ErrorNotice error={edit.error} title="The slot was not saved" />}
          <div className="sx-row">
            <button type="submit" className="sx-btn sm" disabled={edit.isPending}>
              Save
            </button>
            <button type="button" className="sx-btn quiet sm" onClick={() => setDraft(null)}>
              Cancel
            </button>
            {slot.status !== "skipped" && !filled && (
              <button
                type="button"
                className="sx-btn quiet sm"
                disabled={edit.isPending}
                onClick={() => edit.mutate({ ...ref, text: null, skipped: true })}
              >
                Mark as skipped
              </button>
            )}
          </div>
        </form>
      </li>
    );
  }

  const state = slot.status;
  return (
    <li className="outline-slot" data-state={state} data-required={required || undefined} data-testid="outline-slot" data-slot={id}>
      <div className="outline-slot__head">
        <span className="outline-slot__name">
          {/* Inside its step card the step number is said, not shown again. */}
          {view.step !== null && <span className="visually-hidden">Step {view.step + 1}: </span>}
          {SLOT_LABEL[key] ?? key}
        </span>
        <span className="outline-slot__state">
          {state === "filled"
            ? slot.by_user
              ? "Your words"
              : "From your words"
            : state === "skipped"
              ? "Skipped"
              : required
                ? "Empty · needed for Ready"
                : "Empty"}
        </span>
        {!readOnly && (
          <button
            type="button"
            className="sx-btn quiet sm"
            aria-label={`${filled ? "Edit" : "Add"} ${name}`}
            onClick={() =>
              setDraft({
                text: slot.text ?? "",
                before: (slot as { before?: string | null }).before ?? "",
                after: (slot as { after?: string | null }).after ?? "",
              })
            }
          >
            {filled ? "Edit" : "Add"}
          </button>
        )}
      </div>
      {filled && <Markdown className="outline-slot__text" text={slot.text ?? ""} />}
      {filled && metric && <MetricLine slot={slot} />}
    </li>
  );
}

// --- SC-10: the action steps --------------------------------------------------------------------

function Steps({ story, section, readOnly }: { story: Story; section: Section; readOnly?: boolean }) {
  const save = useSaveStory(story);
  const steps = section.steps ?? [];
  const order = useMutation({
    mutationFn: (next: number[]) => storiesApi.editOutline(story.id, { slots: [], steps: next }),
    onSuccess: save,
  });
  const add = useMutation({
    mutationFn: () =>
      storiesApi.editOutline(story.id, {
        slots: [{ section: "action", slot: "did", step: steps.length, text: "", skipped: false }],
      }),
    onSuccess: save,
  });
  const move = (from: number, to: number) => {
    const next = steps.map((_, i) => i);
    [next[from], next[to]] = [next[to], next[from]];
    order.mutate(next);
  };
  const busy = order.isPending || add.isPending;
  return (
    <ol className="plain-list outline-steps" aria-label="Action steps">
      {steps.map((step, i) => {
        const views: SlotView[] = STEP_FIELDS.map((key) => ({
          section: "action",
          key,
          step: i,
          slot: step[key] ?? EMPTY_SLOT,
        }));
        const shown = views.filter((v) => isFilled(v.slot) || v.key === "did" || v.key === "why");
        const quiet = views.filter((v) => !shown.includes(v));
        return (
          <li key={i} className="outline-step" data-testid="outline-step">
            <div className="outline-step__head">
              <span className="outline-step__n">Step {i + 1}</span>
              {!readOnly && (
                <div className="sx-row">
                  <button type="button" className="sx-btn quiet sm" disabled={busy || i === 0} onClick={() => move(i, i - 1)} aria-label={`Move step ${i + 1} up`}>
                    Up
                  </button>
                  <button
                    type="button"
                    className="sx-btn quiet sm"
                    disabled={busy || i === steps.length - 1}
                    onClick={() => move(i, i + 1)}
                    aria-label={`Move step ${i + 1} down`}
                  >
                    Down
                  </button>
                  <button
                    type="button"
                    className="sx-btn quiet sm"
                    disabled={busy || steps.length === 1}
                    onClick={() => order.mutate(steps.map((_, j) => j).filter((j) => j !== i))}
                    aria-label={`Remove step ${i + 1}`}
                  >
                    Remove
                  </button>
                </div>
              )}
            </div>
            <ul className="plain-list outline-section__slots">
              {(readOnly ? views.filter((v) => isFilled(v.slot) || v.key === "did" || v.key === "why") : [...shown, ...quiet]).map((v) => (
                <SlotRow key={v.key} story={story} view={v} readOnly={readOnly} />
              ))}
            </ul>
          </li>
        );
      })}
      {!readOnly && steps.length < MAX_STEPS && (
        <li>
          <button type="button" className="sx-btn ghost sm" disabled={busy} onClick={() => add.mutate()}>
            Add a step
          </button>
        </li>
      )}
      {(order.isError || add.isError) && <ErrorNotice error={order.error ?? add.error} title="The steps were not saved" />}
    </ol>
  );
}

// --- SC-11: Improve with Strova ------------------------------------------------------------------

function ImprovePanel({ story, section, onClose }: { story: Story; section: StorySection; onClose: () => void }) {
  const save = useSaveStory(story);
  const [note, setNote] = useState("");
  const [result, setResult] = useState<SectionImprove | null>(null);
  const [done, setDone] = useState<string[]>([]);
  const ask = useMutation({
    mutationFn: () => storiesApi.improve(story.id, section, note.trim() || null),
    onSuccess: (out) => {
      setResult(out);
      setDone([]);
    },
  });
  const accept = useMutation({
    mutationFn: (edit: SlotEdit) => storiesApi.acceptImprove(story.id, section, [edit], note.trim() || null),
    onSuccess: (saved, edit) => {
      save(saved);
      setDone((d) => [...d, editKey(edit)]);
    },
  });
  const label = SECTION_LABEL[section];
  const open = (result?.edits ?? []).filter((e) => !done.includes(editKey(e)));
  return (
    <div className="sx-card tight coach improve-panel" role="region" aria-label={`Improve ${label} with Strova`}>
      {!result ? (
        <form
          className="sx-stack"
          onSubmit={(e) => {
            e.preventDefault();
            ask.mutate();
          }}
        >
          <label htmlFor={`improve-note-${section}`} className="sx-small">
            A note for Strova (optional)
          </label>
          <input
            id={`improve-note-${section}`}
            value={note}
            maxLength={1000}
            placeholder="For example: make it shorter, or lead with the result"
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="sx-row">
            <button type="submit" className="sx-btn sm" disabled={ask.isPending}>
              {ask.isPending ? "Strova is reading" : `Improve ${label}`}
            </button>
            <button type="button" className="sx-btn quiet sm" onClick={onClose}>
              Cancel
            </button>
          </div>
          {ask.isError && <ErrorNotice error={ask.error} title="Strova could not improve this section" />}
        </form>
      ) : (
        <div className="sx-stack">
          <div className="sx-row">
            <Strova mode="coaching" size={28} />
            <span className="sx-small">Strova's edits use only your words. Accept or reject each one.</span>
          </div>
          {open.map((e) => (
            <div key={editKey(e)} className="sx-card tight" role="group" aria-label={`Edit to ${slotName({ key: e.slot, step: e.step })}`}>
              <span className="sx-eyebrow">{slotName({ key: e.slot, step: e.step })}</span>
              <div className="sx-diff">
                {e.before && (
                  <>
                    <del>{e.before}</del>
                    <br />
                  </>
                )}
                <ins>{e.after}</ins>
              </div>
              <div className="sx-row">
                <button type="button" className="sx-btn sm" disabled={accept.isPending} onClick={() => accept.mutate(e)}>
                  Accept
                </button>
                <button type="button" className="sx-btn quiet sm" onClick={() => setDone((d) => [...d, editKey(e)])}>
                  Reject
                </button>
              </div>
            </div>
          ))}
          {result.questions.length > 0 && (
            <div className="sx-notice v sx-small" data-testid="improve-questions">
              <strong>Strova needs a few facts first:</strong>
              <ul>
                {result.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
              <Link to={newCoachPath({ story: story.id })}>Answer with Strova</Link>
            </div>
          )}
          {open.length === 0 && result.questions.length === 0 && (
            <p className="sx-small sx-muted" role="status">
              Done. {label} is up to date.
            </p>
          )}
          {accept.isError && <ErrorNotice error={accept.error} title="The edit was not applied" />}
          <div>
            <button type="button" className="sx-btn quiet sm" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const editKey = (e: { section: string; slot: string; step?: number | null }) => `${e.section}.${e.slot}.${e.step ?? ""}`;

// --- the outline --------------------------------------------------------------------------------

function SectionCard({ story, outline, section, readOnly }: { story: Story; outline: StoryOutline; section: Section; readOnly?: boolean }) {
  const [improving, setImproving] = useState(false);
  const label = SECTION_LABEL[section.section];
  const views = sectionSlots(outline, section);
  const shown = views.filter((v) => v.slot.status !== "empty" || CORE_SLOTS.has(v.key) || CONTEXT_SLOTS.has(v.key));
  const quiet = views.filter((v) => !shown.includes(v));
  const headingId = `outline-${section.section}-${readOnly ? "preview" : "story"}`;
  return (
    <div role="group" className="outline-section" aria-labelledby={headingId} data-testid="outline-section" data-section={section.section}>
      <div className="outline-section__head">
        <h2 id={headingId}>{label}</h2>
        {!readOnly && !improving && (
          <button type="button" className="sx-btn ghost sm" onClick={() => setImproving(true)}>
            Improve with Strova
          </button>
        )}
      </div>
      {improving && <ImprovePanel story={story} section={section.section} onClose={() => setImproving(false)} />}
      {section.section === "action" ? (
        <Steps story={story} section={section} readOnly={readOnly} />
      ) : (
        <>
          <ul className="plain-list outline-section__slots">
            {(readOnly ? views.filter((v) => isFilled(v.slot)) : shown).map((v) => (
              <SlotRow key={v.key} story={story} view={v} readOnly={readOnly} />
            ))}
          </ul>
          {!readOnly && quiet.length > 0 && <QuietSlots story={story} views={quiet} />}
        </>
      )}
    </div>
  );
}

/** Empty optional slots: one quiet line, each a button that opens its editor. */
function QuietSlots({ story, views }: { story: Story; views: SlotView[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const chosen = views.find((v) => v.key === open);
  return (
    <div className="outline-quiet sx-small sx-muted">
      {chosen ? (
        <ul className="plain-list outline-section__slots">
          <SlotRow key={chosen.key} story={story} view={chosen} startEditing />
        </ul>
      ) : (
        <>
          Also, if you have them:{" "}
          {views.map((v, i) => (
            <span key={v.key}>
              {i > 0 && ", "}
              <button type="button" className="text-button" onClick={() => setOpen(v.key)}>
                {SLOT_LABEL[v.key] ?? v.key}
              </button>
            </span>
          ))}
        </>
      )}
    </div>
  );
}

export function OutlineStory({ story, outline, readOnly }: { story: Story; outline: StoryOutline; readOnly?: boolean }) {
  return (
    <div className="outline-story" data-testid={readOnly ? "outline-preview" : "outline-story"}>
      {outline.sections.map((section) => (
        <SectionCard key={section.section} story={story} outline={outline} section={section} readOnly={readOnly} />
      ))}
    </div>
  );
}

// --- SC-12: Switch to STAR or CARL ---------------------------------------------------------------

export function StyleSwitch({ story, outline }: { story: Story; outline: StoryOutline }) {
  const save = useSaveStory(story);
  const other = outline.style === "star" ? "carl" : "star";
  const [rewrite, setRewrite] = useState(false);
  const [preview, setPreview] = useState<StoryOutline | null>(null);
  const run = useMutation({
    mutationFn: () => storiesApi.switchStyle(story.id, other, rewrite),
    onSuccess: (out) => {
      if (out.story) save(out.story);
      else if (out.preview) setPreview(out.preview as StoryOutline);
    },
  });
  const accept = useMutation({
    mutationFn: (next: StoryOutline) => storiesApi.acceptStyle(story.id, next),
    onSuccess: (saved) => {
      save(saved);
      setPreview(null);
    },
  });
  if (preview) {
    return (
      <div className="sx-card tight coach" role="region" aria-label={`${STYLE_NAME[other]} preview`}>
        <div className="sx-row">
          <span className="sx-chip v" data-testid="story-style">
            {STYLE_NAME[outline.style]}
          </span>
          <span className="sx-eyebrow">Preview · {STYLE_NAME[other]}, reworded by Strova</span>
        </div>
        <span className="sx-small sx-muted">Nothing changes until you accept. Every fact is still yours.</span>
        <OutlineStory story={story} outline={preview} readOnly />
        <div className="sx-row">
          <button type="button" className="sx-btn sm" disabled={accept.isPending} onClick={() => accept.mutate(preview)}>
            Accept
          </button>
          <button type="button" className="sx-btn quiet sm" onClick={() => setPreview(null)}>
            Discard
          </button>
        </div>
        {accept.isError && <ErrorNotice error={accept.error} title="The new style was not saved" />}
      </div>
    );
  }
  return (
    <div className="sx-row style-switch">
      <span className="sx-chip v" data-testid="story-style">
        {STYLE_NAME[outline.style]}
      </span>
      <button type="button" className="sx-btn ghost sm" disabled={run.isPending} onClick={() => run.mutate()}>
        {run.isPending ? "Switching" : `Switch to ${STYLE_NAME[other]}`}
      </button>
      <label className="sx-small style-switch__rewrite">
        <input type="checkbox" checked={rewrite} onChange={(e) => setRewrite(e.target.checked)} /> Rewrite the wording too
      </label>
      {run.isError && <ErrorNotice error={run.error} title="The style did not change" />}
    </div>
  );
}

// --- SC-13: Organize with Strova -----------------------------------------------------------------

export function OrganizeBanner({ story }: { story: Story }) {
  const save = useSaveStory(story);
  const [preview, setPreview] = useState<StoryOutline | null>(null);
  const run = useMutation({
    mutationFn: () => storiesApi.organize(story.id),
    onSuccess: (out) => setPreview(out.outline as StoryOutline),
  });
  const accept = useMutation({
    mutationFn: (outline: StoryOutline) => storiesApi.acceptOrganize(story.id, { outline } as never),
    onSuccess: (saved) => {
      save(saved);
      setPreview(null);
    },
  });
  if (preview) {
    return (
      <div className="sx-card tight coach" role="region" aria-label="Organized preview">
        <span className="sx-eyebrow">Preview · STAR, from your words</span>
        <span className="sx-small sx-muted">Nothing changes until you accept.</span>
        <OutlineStory story={story} outline={preview} readOnly />
        <div className="sx-row">
          <button type="button" className="sx-btn sm" disabled={accept.isPending} onClick={() => accept.mutate(preview)}>
            Accept
          </button>
          <button type="button" className="sx-btn quiet sm" onClick={() => setPreview(null)}>
            Discard
          </button>
        </div>
        {accept.isError && <ErrorNotice error={accept.error} title="The story was not organized" />}
      </div>
    );
  }
  return (
    <div className="sx-notice v organize-banner" role="region" aria-label="Organize with Strova">
      <Strova mode="coaching" size={28} />
      <span className="sx-small">
        Strova can sort this story into STAR sections and slots, from your words only. You see a preview first.
      </span>
      <button type="button" className="sx-btn sm" disabled={run.isPending} onClick={() => run.mutate()}>
        {run.isPending ? "Strova is organizing" : "Organize with Strova"}
      </button>
      {run.isError && <ErrorNotice error={run.error} title="Strova could not organize the story" />}
    </div>
  );
}
