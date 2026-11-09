/**
 * Career Stories (docs/stories-redesign/spec.md). Stories come first: one list of the user's
 * stories and the stories Strova recommends writing (CS-5), with filter chips (CS-6), skill
 * coverage that filters the list (CS-7), "+ New story" with its two ways to start (CS-8), Start
 * on each recommendation (CS-9), job tips on the story they belong to (CS-10), job skill gaps as
 * recommendations (CS-11), and rename, archive and delete from the row menu (CS-12 to CS-17).
 * Ask Strova (ST-13) opens in a side panel.
 */
import "../../components/ux/ux.css";
import "./stories.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { keys } from "../../api/hooks";
import { resumesApi } from "../../api/inputs";
import { suggestionKeys, suggestionsApi, useSuggestions } from "../../api/suggestions";
import type { Suggestion } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import { ProvenSeal } from "../../components/ux/Seal";
import { competencyLabel } from "../../labels";
import { newCoachPath } from "../coach/paths";
import { craftFromIdeaPath } from "../onboarding/check/StoriesStep";
import {
  displayStatusLabel,
  filledParts,
  storiesApi,
  storyKeys,
  useStories,
  useStoryRecommendations,
  type Competency,
  type DisplayStatus,
  type RecommendedIdea,
  type RecommendedSkill,
  type Story,
  type StoryAnswer,
} from "./api";
import { newStoryPath, storyPath } from "./paths";

/** The skills Career Stories maps first: the behavioral ones, then any other tag in use. */
const CORE_SKILLS: Competency[] = [
  "ownership",
  "impact",
  "collaboration",
  "conflict_handling",
  "learning_from_failure",
  "communication",
];

type Coverage = "covered" | "thin" | "missing";

/** ST-9: covered by a Ready or Proven story, thin when only drafts show it, else missing. CS-7:
 * pass only the stories in prep (not archived). */
export function skillCoverage(stories: Story[]): { skill: Competency; coverage: Coverage }[] {
  const tagged = stories.flatMap((s) => s.skills);
  const skills = [...new Set([...CORE_SKILLS, ...tagged])];
  return skills.map((skill) => {
    const with_ = stories.filter((s) => s.skills.includes(skill));
    const coverage: Coverage = with_.some((s) => s.display_status !== "draft")
      ? "covered"
      : with_.length > 0
        ? "thin"
        : "missing";
    return { skill, coverage };
  });
}

const COVERAGE_CHIP: Record<Coverage, string> = { covered: "ok", thin: "warn", missing: "bad" };
const COVERAGE_MARK: Record<Coverage, string> = { covered: "✓", thin: "~", missing: "✕" };
const STATUS_CHIP: Record<DisplayStatus, string> = { proven: "ok", ready: "v", draft: "" };

export type Show = "all" | "draft" | "ready" | "proven" | "recommended" | "archived";
const FILTERS: { value: Show; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "ready", label: "Ready" },
  { value: "proven", label: "Proven" },
  { value: "recommended", label: "Recommended" },
  { value: "archived", label: "Archived" },
];
const isShow = (v: string | null): v is Show => FILTERS.some((f) => f.value === v);

type Tip = Suggestion;
type Row =
  | { kind: "story"; story: Story; tips: Tip[] }
  | { kind: "idea"; idea: RecommendedIdea }
  | { kind: "skill"; gap: RecommendedSkill };

/** CS-5 sort order: drafts with tips, other drafts (newest first), then Ready and Proven (most
 * recently updated first), then job gaps, then resume ideas in resume order. */
export function sortRows(rows: Row[]): Row[] {
  const rank = (r: Row) => {
    if (r.kind === "skill") return 4;
    if (r.kind === "idea") return 5;
    if (r.story.display_status === "draft") return r.tips.length > 0 ? 0 : 1;
    return 2;
  };
  const stamp = (r: Row) =>
    r.kind !== "story" ? "" : r.story.display_status === "draft" ? r.story.created_at : r.story.updated_at;
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => rank(a.r) - rank(b.r) || stamp(b.r).localeCompare(stamp(a.r)) || a.i - b.i)
    .map(({ r }) => r);
}

const rowSkills = (r: Row): string[] =>
  r.kind === "story" ? r.story.skills : r.kind === "idea" ? r.idea.skills : [r.gap.competency];

function matchesShow(r: Row, show: Show): boolean {
  if (show === "recommended") return r.kind !== "story";
  if (show === "archived") return r.kind === "story" && !!r.story.archived_at;
  if (r.kind === "story" && r.story.archived_at) return false;
  if (show === "all") return true;
  return r.kind === "story" && r.story.display_status === show;
}

export function CareerStoriesPage() {
  const stories = useStories({ include: ["archived", "deleted"] });
  const recs = useStoryRecommendations();
  const tips = useSuggestions("stories");
  const [params, setParams] = useSearchParams();
  const show: Show = isShow(params.get("show")) ? (params.get("show") as Show) : "all";
  const [skill, setSkill] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [undo, setUndo] = useState<Story | null>(null);
  const clearUndo = useCallback(() => setUndo(null), []);
  const closeAsk = useCallback(() => setAsking(false), []);

  const all = stories.data ?? [];
  const deleted = all.filter((s) => s.deleted_at);
  const kept = all.filter((s) => !s.deleted_at);
  const inPrep = kept.filter((s) => !s.archived_at);
  const tipsFor = (id: string) =>
    (tips.data ?? []).filter((t) => t.story_id === id && (t.kind === "tailor_role" || t.kind === "tune_story"));
  const rows: Row[] = [
    ...kept.map((story): Row => ({ kind: "story", story, tips: story.archived_at ? [] : tipsFor(story.id) })),
    ...(recs.data?.skills ?? []).map((gap): Row => ({ kind: "skill", gap })),
    ...(recs.data?.ideas ?? []).map((idea): Row => ({ kind: "idea", idea })),
  ];
  const shown = sortRows(rows.filter((r) => matchesShow(r, show) && (!skill || rowSkills(r).includes(skill))));
  const setShow = (next: Show) => {
    const p = new URLSearchParams(params);
    if (next === "all") p.delete("show");
    else p.set("show", next);
    setParams(p, { replace: true });
  };
  const loading = stories.isPending || recs.isPending;
  const nothing = !loading && kept.length === 0 && rows.length === 0;

  return (
    <div className="sx-page career-stories">
      <div className="career-stories__head">
        <div className="sx-row">
          <Strova mode="coaching" size={56} />
          <div>
            <h1>Career stories</h1>
            <p className="sx-muted sx-small">The moments you'll tell in "tell me about a time…" questions.</p>
          </div>
        </div>
        <div className="sx-row career-stories__actions">
          <button type="button" className="sx-btn ghost sm" onClick={() => setAsking(true)}>
            Ask Strova
          </button>
          <StartButton label="+ New story" craft={newCoachPath()} write={newStoryPath()} menuLabel="More ways to start" />
        </div>
      </div>

      {inPrep.length > 0 && (
        <div className="career-stories__bar">
          <div className="sx-chips" role="group" aria-label="Skill coverage">
            {skillCoverage(inPrep).map(({ skill: s, coverage }) => (
              <button
                key={s}
                type="button"
                className={`sx-chip ${COVERAGE_CHIP[coverage]} career-stories__chip`}
                aria-pressed={skill === s}
                aria-label={`${competencyLabel(s)}: ${coverage}`}
                onClick={() => {
                  setSkill(skill === s ? null : s);
                  if (show === "archived") setShow("all");
                }}
              >
                {competencyLabel(s)} {COVERAGE_MARK[coverage]}
              </button>
            ))}
          </div>
        </div>
      )}
      {!nothing && (
        <div className="sx-chips career-stories__filters" role="group" aria-label="Show">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              className={`sx-chip career-stories__chip ${show === f.value ? "dark" : ""}`}
              aria-pressed={show === f.value}
              onClick={() => setShow(f.value)}
            >
              {f.label} {rows.filter((r) => matchesShow(r, f.value)).length}
            </button>
          ))}
        </div>
      )}

      {loading && <Loading label="Loading your stories" />}
      {stories.isError && <ErrorNotice error={stories.error} />}
      {recs.isError && <ErrorNotice error={recs.error} />}

      {nothing && (
        <section className="sx-card sx-stack" data-testid="stories-empty" aria-label="No stories yet">
          <p className="sx-small sx-muted">
            <b>No stories yet.</b> A story is one moment from your career, told in 5 parts, ready for "tell me about a
            time…" questions. Strova builds the first one with you, from your own words.
          </p>
          <div>
            <Link className="sx-btn sm" to={newCoachPath()}>
              Build my first story
            </Link>
          </div>
        </section>
      )}

      {!loading && !nothing && (
        <section className="sx-card career-stories__list" aria-label="Stories">
          {kept.length === 0 && show === "all" && !skill && (
            <p className="sx-small sx-muted career-stories__hint">Strova found these in your resume. Start with one.</p>
          )}
          {shown.length === 0 ? (
            <p className="sx-small sx-muted career-stories__none">
              No {FILTERS.find((f) => f.value === show)?.label.toLowerCase()} stories
              {skill ? ` for ${competencyLabel(skill as Competency)}` : ""}.{" "}
              <button
                type="button"
                className="career-stories__link"
                onClick={() => {
                  setSkill(null);
                  setShow("all");
                }}
              >
                Show all
              </button>
            </p>
          ) : (
            <ul className="plain-list">
              {shown.map((r) =>
                r.kind === "story" ? (
                  <StoryRow key={r.story.id} story={r.story} tips={r.tips} onDeleted={setUndo} />
                ) : r.kind === "idea" ? (
                  <IdeaRow key={`${r.idea.resume_id}:${r.idea.resume_line_ref}`} idea={r.idea} />
                ) : (
                  <SkillRow key={r.gap.suggestion_id} gap={r.gap} />
                ),
              )}
            </ul>
          )}
          {show === "archived" && deleted.length > 0 && <RecentlyDeleted stories={deleted} />}
        </section>
      )}

      {asking && <AskPanel stories={inPrep} onClose={closeAsk} />}
      {undo && <UndoToast story={undo} onDone={clearUndo} />}
    </div>
  );
}

/** CS-8, CS-9: a split button. The main part crafts with Strova; the menu also offers Write it
 * yourself. */
function StartButton({
  label,
  craft,
  write,
  menuLabel,
  small = false,
}: {
  label: string;
  craft: string;
  write: string;
  menuLabel: string;
  small?: boolean;
}) {
  return (
    <span className="career-stories__split">
      <Link className={`sx-btn ${small ? "sm" : ""}`} to={craft}>
        {label}
      </Link>
      <details className="sx-menu">
        <summary className={`sx-btn ${small ? "sm" : ""} career-stories__caret`} aria-label={menuLabel}>
          ▾
        </summary>
        <div className="sx-menu__list career-stories__menu" role="menu">
          <Link role="menuitem" to={craft}>
            <b>Craft with Strova</b>
            <span className="sx-small sx-muted">Strova asks, you answer. Talk or type.</span>
          </Link>
          <Link role="menuitem" to={write}>
            <b>Write it yourself</b>
            <span className="sx-small sx-muted">Write or paste the five parts. Strova can review after.</span>
          </Link>
        </div>
      </details>
    </span>
  );
}

function useRefreshStories() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: storyKeys.all });
    void client.invalidateQueries({ queryKey: suggestionKeys.place("stories") });
  };
}

function StoryRow({ story, tips, onDeleted }: { story: Story; tips: Tip[]; onDeleted: (s: Story) => void }) {
  const refresh = useRefreshStories();
  const [renaming, setRenaming] = useState(false);
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDetailsElement>(null);
  const close = () => menu.current?.removeAttribute("open");
  const act = useMutation({
    mutationFn: async (what: "archive" | "unarchive" | "delete") => {
      if (what === "archive") await storiesApi.archive(story.id);
      else if (what === "unarchive") await storiesApi.unarchive(story.id);
      else await storiesApi.remove(story.id);
      return what;
    },
    onSuccess: (what) => {
      refresh();
      if (what === "delete") onDeleted(story);
    },
  });
  const rename = useMutation({
    mutationFn: (title: string) => storiesApi.update(story.id, { title }),
    onSuccess: () => {
      setRenaming(false);
      refresh();
    },
  });
  const archived = !!story.archived_at;
  const filled = filledParts(story).length;
  const meta = [
    story.skills.map(competencyLabel).join(", "),
    story.display_status === "draft" ? `${filled} of 5 parts` : null,
    story.source === "manual" ? "you wrote it" : null,
    archived ? `Archived ${new Date(story.archived_at as string).toLocaleDateString()}` : null,
  ].filter(Boolean);
  const byTag = groupTips(tips);

  return (
    <li data-testid="story-row" className={`career-stories__row ${archived ? "is-archived" : ""}`}>
      <div className="career-stories__main">
        {renaming ? (
          <RenameField
            title={story.title}
            busy={rename.isPending}
            onSave={(t) => rename.mutate(t)}
            onCancel={() => setRenaming(false)}
          />
        ) : (
          <Link className="career-stories__title" to={storyPath(story.id)}>
            {story.title}
          </Link>
        )}
        {meta.length > 0 && <span className="sx-small sx-muted">{meta.join(" · ")}</span>}
        {(rename.error ?? act.error) && (
          <span className="sx-small" role="alert">
            {(rename.error ?? act.error)?.message}
          </span>
        )}
      </div>
      <div className="career-stories__side">
        {[...byTag.entries()].map(([tag, list]) => (
          <button
            key={tag}
            type="button"
            className="sx-chip t career-stories__chip"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {tag} {list.length}
          </button>
        ))}
        <span className={`sx-chip ${STATUS_CHIP[story.display_status]}`}>
          {story.display_status === "proven" && <ProvenSeal size={14} />}
          {displayStatusLabel[story.display_status]}
        </span>
        <details className="sx-menu" ref={menu}>
          <summary className="sx-btn quiet sm" aria-label={`More for ${story.title}`}>
            ⋯
          </summary>
          <div className="sx-menu__list" role="menu">
            {!archived && (
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  close();
                  setRenaming(true);
                }}
              >
                Rename
              </button>
            )}
            <button
              type="button"
              role="menuitem"
              disabled={act.isPending}
              onClick={() => {
                close();
                act.mutate(archived ? "unarchive" : "archive");
              }}
            >
              {archived ? "Unarchive" : "Archive"}
            </button>
            <button
              type="button"
              role="menuitem"
              className="career-stories__danger"
              disabled={act.isPending}
              onClick={() => {
                close();
                // CS-17: ask first.
                if (window.confirm(`Delete "${story.title}"? You can undo this for 30 days.`)) act.mutate("delete");
              }}
            >
              Delete
            </button>
          </div>
        </details>
      </div>
      {open && tips.length > 0 && (
        <div className="career-stories__tips" role="region" aria-label={`Tips for ${story.title}`}>
          {tips.map((t) => (
            <TipRow key={t.id} tip={t} storyId={story.id} />
          ))}
        </div>
      )}
    </li>
  );
}

/** CS-10: tips per company ("Tips: Stripe"), and Strova's tuning ("Tune"). */
function groupTips(tips: Tip[]): Map<string, Tip[]> {
  const out = new Map<string, Tip[]>();
  for (const t of tips) {
    const tag = t.payload.kind === "tailor_role" ? `Tips: ${t.payload.company}` : "Tune";
    out.set(tag, [...(out.get(tag) ?? []), t]);
  }
  return out;
}

function TipRow({ tip, storyId }: { tip: Tip; storyId: string }) {
  const refresh = useRefreshStories();
  const accept = useMutation({ mutationFn: () => suggestionsApi.accept(tip.id), onSuccess: refresh });
  const dismiss = useMutation({ mutationFn: () => suggestionsApi.dismiss(tip.id), onSuccess: refresh });
  const busy = accept.isPending || dismiss.isPending;
  const p = tip.payload;
  return (
    <div className="career-stories__tip" role="group" aria-label={p.kind === "tailor_role" ? `For ${p.company}` : "Tune"}>
      <span className="sx-small">
        <b className="career-stories__tip-tag">{p.kind === "tailor_role" ? `For ${p.company}` : "Tune"}</b>
        {p.kind === "tailor_role" ? p.note : tip.reason}
      </span>
      <span className="sx-row">
        {p.kind === "tailor_role" ? (
          <button type="button" className="sx-btn ghost sm" disabled={busy} onClick={() => accept.mutate()}>
            Add to notes
          </button>
        ) : (
          <Link className="sx-btn ghost sm" to={storyPath(storyId)}>
            Review
          </Link>
        )}
        <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => dismiss.mutate()}>
          Dismiss
        </button>
      </span>
      {(accept.error ?? dismiss.error) && (
        <span className="sx-small" role="alert">
          {(accept.error ?? dismiss.error)?.message}
        </span>
      )}
    </div>
  );
}

/** CS-12: rename in place. Enter saves, Escape cancels; an empty title is refused. */
function RenameField({
  title,
  busy,
  onSave,
  onCancel,
}: {
  title: string;
  busy: boolean;
  onSave: (t: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(title);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);
  const keyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") onCancel();
    if (e.key === "Enter") {
      e.preventDefault();
      if (value.trim()) onSave(value.trim());
    }
  };
  return (
    <input
      ref={input}
      className="career-stories__rename"
      aria-label="Story name"
      value={value}
      maxLength={200}
      disabled={busy}
      aria-invalid={!value.trim() || undefined}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={keyDown}
      onBlur={onCancel}
    />
  );
}

/** CS-1, CS-4, CS-9: a resume achievement no story tells yet, pooled across resumes. */
function IdeaRow({ idea }: { idea: RecommendedIdea }) {
  const client = useQueryClient();
  const dismiss = useMutation({
    mutationFn: () => resumesApi.dismissIdea(idea.resume_id, idea.resume_line_ref),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: storyKeys.recommendations });
      void client.invalidateQueries({ queryKey: keys.storyIdeas(idea.resume_id) });
    },
  });
  const from = idea.resumes > 1 ? `From ${idea.resumes} resumes` : "From your resume";
  return (
    <RecommendedRow
      title={idea.achievement}
      meta={<>{[from, ...idea.skills.map(competencyLabel)].join(" · ")}</>}
      craft={craftFromIdeaPath(idea.resume_id, idea.resume_line_ref)}
      write={newStoryPath(undefined, { text: idea.achievement, skills: idea.skills })}
      busy={dismiss.isPending}
      error={dismiss.error}
      onDismiss={() => dismiss.mutate()}
    />
  );
}

/** CS-11: a skill one of the user's target roles tests that no story covers. */
function SkillRow({ gap }: { gap: RecommendedSkill }) {
  const client = useQueryClient();
  const dismiss = useMutation({
    mutationFn: () => suggestionsApi.dismiss(gap.suggestion_id),
    onSuccess: () => void client.invalidateQueries({ queryKey: storyKeys.recommendations }),
  });
  const job = [gap.company, gap.job_title].filter(Boolean).join(" – ");
  return (
    <RecommendedRow
      title={`${competencyLabel(gap.competency)} story`}
      meta={
        <>
          {job && <span className="sx-chip warn">For {job}</span>} <span>{gap.reason}</span>
        </>
      }
      craft={newCoachPath({ skill: gap.competency, job: gap.job_target_id })}
      write={newStoryPath(gap.competency)}
      busy={dismiss.isPending}
      error={dismiss.error}
      onDismiss={() => dismiss.mutate()}
    />
  );
}

function RecommendedRow({
  title,
  meta,
  craft,
  write,
  busy,
  error,
  onDismiss,
}: {
  title: string;
  meta: ReactNode;
  craft: string;
  write: string;
  busy: boolean;
  error: Error | null;
  onDismiss: () => void;
}) {
  return (
    <li data-testid="recommended-row" className="career-stories__row is-recommended">
      <div className="career-stories__main">
        <strong>{title}</strong>
        <span className="sx-small sx-muted career-stories__meta">{meta}</span>
        {error && (
          <span className="sx-small" role="alert">
            {error.message}
          </span>
        )}
      </div>
      <div className="career-stories__side">
        <span className="sx-chip career-stories__rec">Recommended</span>
        <StartButton label="Start" craft={craft} write={write} menuLabel={`More ways to start: ${title}`} small />
        <button
          type="button"
          className="sx-btn quiet sm"
          aria-label={`Dismiss: ${title}`}
          disabled={busy}
          onClick={onDismiss}
        >
          ✕
        </button>
      </div>
    </li>
  );
}

/** CS-15: deleted stories, restorable for 30 days, under the Archived filter. */
function RecentlyDeleted({ stories }: { stories: Story[] }) {
  const refresh = useRefreshStories();
  const restore = useMutation({ mutationFn: (id: string) => storiesApi.restore(id), onSuccess: refresh });
  return (
    <details className="career-stories__deleted" data-testid="recently-deleted">
      <summary className="sx-small sx-muted">Recently deleted ({stories.length}) · restorable for 30 days</summary>
      <ul className="plain-list">
        {stories.map((s) => (
          <li key={s.id} className="sx-between">
            <span className="sx-small">{s.title}</span>
            <button
              type="button"
              className="sx-btn ghost sm"
              disabled={restore.isPending}
              onClick={() => restore.mutate(s.id)}
            >
              Restore
            </button>
          </li>
        ))}
      </ul>
      {restore.isError && <ErrorNotice error={restore.error} />}
    </details>
  );
}

/** CS-15: "Deleted. Undo" for 10 seconds after a delete. */
function UndoToast({ story, onDone }: { story: Story; onDone: () => void }) {
  const refresh = useRefreshStories();
  const restore = useMutation({
    mutationFn: () => storiesApi.restore(story.id),
    onSuccess: () => {
      refresh();
      onDone();
    },
  });
  useEffect(() => {
    const t = window.setTimeout(onDone, 10_000);
    return () => window.clearTimeout(t);
  }, [onDone, story.id]);
  return (
    <div className="career-stories__toast" role="status">
      <span>Deleted "{story.title}".</span>
      <button type="button" disabled={restore.isPending} onClick={() => restore.mutate()}>
        Undo
      </button>
    </div>
  );
}

/** D-5: Ask Strova in a side panel. */
function AskPanel({ stories, onClose }: { stories: Story[]; onClose: () => void }) {
  useEffect(() => {
    const esc = (e: globalThis.KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <aside className="career-stories__panel" aria-label="Ask Strova panel">
      <div className="sx-between">
        <strong>Ask Strova</strong>
        <button type="button" className="sx-btn quiet sm" aria-label="Close Ask Strova" onClick={onClose}>
          ✕
        </button>
      </div>
      <p className="sx-small sx-muted">Answers come from your own stories and target roles.</p>
      <AskStrova stories={stories} />
    </aside>
  );
}

/** ST-13: Ask Strova, answered from the user's own stories and roles. */
export function AskStrova({ stories }: { stories: Story[] }) {
  const [question, setQuestion] = useState("");
  const ask = useMutation({ mutationFn: (q: string) => storiesApi.ask(q) });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (question.trim()) ask.mutate(question.trim());
  };
  return (
    <>
      <form className="sx-card tight career-stories__ask" onSubmit={submit} aria-label="Ask Strova">
        <Strova mode="coaching" size={28} />
        <label htmlFor="askstrova" className="sx-small">
          Ask Strova
        </label>
        <input
          id="askstrova"
          value={question}
          maxLength={500}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Which story should I use for leadership at Stripe?"
        />
        <button className="sx-btn sm" type="submit" disabled={ask.isPending || !question.trim()}>
          Ask
        </button>
      </form>
      {ask.isPending && <Loading label="Strova is thinking" />}
      {ask.isError && <ErrorNotice error={ask.error} />}
      {ask.data && <AskAnswer answer={ask.data} stories={stories} />}
    </>
  );
}

function AskAnswer({ answer, stories }: { answer: StoryAnswer; stories: Story[] }) {
  const named = answer.story_ids.map((id) => stories.find((s) => s.id === id)).filter((s): s is Story => !!s);
  return (
    <section className="sx-card coach" aria-label="Strova's answer" role="region">
      <div className="sx-row">
        <Strova mode="coaching" size={28} />
        <p>{answer.answer}</p>
      </div>
      {named.length > 0 && (
        <p className="sx-small">
          {named.map((s, i) => (
            <span key={s.id}>
              {i > 0 && " · "}
              <Link to={storyPath(s.id)}>{s.title}</Link>
            </span>
          ))}
        </p>
      )}
    </section>
  );
}
