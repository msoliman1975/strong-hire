/**
 * ST-9 (mockup #stories): Career Stories with Strova. In order: start a new story (Craft with
 * Strova, Write it yourself), stories recommended from the resume (collapsed, RM-4), Ask Strova
 * (ST-13), your stories with skill coverage (ST-3, ST-8), and Strova suggests (collapsed, U08,
 * place `stories`).
 */
import "../../components/ux/ux.css";
import "./stories.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";

import { keys, useResumes, useStoryIdeas } from "../../api/hooks";
import { resumesApi } from "../../api/inputs";
import { suggestionKeys, suggestionsApi, useSuggestions } from "../../api/suggestions";
import type { Suggestion } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import { competencyLabel } from "../../labels";
import { newCoachPath } from "../coach/paths";
import { craftFromIdeaPath } from "../resumes/ResumeDetailPage";
import {
  displayStatusLabel,
  filledParts,
  storiesApi,
  useStories,
  type Competency,
  type DisplayStatus,
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

/** ST-9: covered by a Ready or Proven story, thin when only drafts show it, else missing. */
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
const STATUS_CHIP: Record<DisplayStatus, string> = { proven: "ok", ready: "v", draft: "" };

export function CareerStoriesPage() {
  const stories = useStories();
  const list = stories.data ?? [];
  return (
    <div className="sx-page career-stories">
      <div className="sx-row">
        <Strova mode="coaching" size={72} />
        <div>
          <h1>Career Stories with Strova</h1>
          <p className="sx-muted sx-small">
            Build the stories you'll tell in interviews with Strova, who coaches you from your own words.
          </p>
        </div>
      </div>
      <section className="sx-card" aria-labelledby="start-heading">
        <h2 id="start-heading">Start a new story</h2>
        <div className="sx-grid2">
          <Link className="sx-choice v" to={newCoachPath()}>
            <span className="sx-row">
              <Strova mode="coaching" size={28} />
              <span className="sx-eyebrow">Craft with Strova</span>
            </span>
            <h3>Strova asks, you answer</h3>
            <span className="sx-small">Talk or type. The five parts fill in from your own words.</span>
          </Link>
          <Link className="sx-choice" to={newStoryPath()}>
            <span className="sx-eyebrow plain">Write it yourself</span>
            <h3>Write the five parts</h3>
            <span className="sx-small sx-muted">
              Write or paste your story. When you're done, Strova can review it and suggest edits.
            </span>
          </Link>
        </div>
      </section>
      <ResumeIdeas />
      <AskStrova stories={list} />
      <section className="sx-card" aria-labelledby="your-stories-heading">
        <div className="sx-between">
          <h2 id="your-stories-heading">Your stories</h2>
          {list.length > 0 && <span className="sx-small sx-muted">{statusCounts(list)}</span>}
        </div>
        {stories.isPending && <Loading label="Loading your stories" />}
        {stories.isError && <ErrorNotice error={stories.error} />}
        {stories.data && list.length === 0 && (
          <div className="sx-stack" data-testid="stories-empty">
            <p className="sx-small sx-muted">
              <b>No stories yet.</b> A story is one moment from your career, told in 5 parts, ready for "tell me about a
              time…" questions. Strova builds the first one with you, from your own words.
            </p>
            <div>
              <Link className="sx-btn sm" to={newCoachPath()}>
                Build my first story
              </Link>
            </div>
          </div>
        )}
        {list.length > 0 && (
          <>
            <div className="sx-chips" aria-label="Skill coverage" role="list">
              {skillCoverage(list).map(({ skill, coverage }) => (
                <span key={skill} role="listitem" className={`sx-chip ${COVERAGE_CHIP[coverage]}`}>
                  {competencyLabel(skill)} · {coverage}
                </span>
              ))}
            </div>
            <ul className="plain-list" aria-label="Stories">
              {list.map((s) => (
                <StoryRow key={s.id} story={s} />
              ))}
            </ul>
          </>
        )}
      </section>
      <StrovaSuggests />
    </div>
  );
}

function statusCounts(list: Story[]): string {
  const order: DisplayStatus[] = ["proven", "ready", "draft"];
  return order
    .map((st) => [st, list.filter((s) => s.display_status === st).length] as const)
    .filter(([, n]) => n > 0)
    .map(([st, n]) => `${n} ${displayStatusLabel[st]}`)
    .join(" · ");
}

function StoryRow({ story }: { story: Story }) {
  const filled = filledParts(story).length;
  const meta = [
    story.skills.map(competencyLabel).join(", "),
    story.display_status === "draft" ? `${filled} of 5 parts` : null,
    story.source === "manual" ? "you wrote it" : null,
  ].filter(Boolean);
  return (
    <li data-testid="story-row">
      <Link className="sx-list-row" to={storyPath(story.id)}>
        <span className="sx-stack career-stories__row">
          <strong>{story.title}</strong>
          {meta.length > 0 && <span className="sx-small sx-muted">{meta.join(" · ")}</span>}
        </span>
        <span className={`sx-chip ${STATUS_CHIP[story.display_status]}`}>
          {displayStatusLabel[story.display_status]}
        </span>
      </Link>
    </li>
  );
}

/** RM-4 on Career Stories: the main resume's achievements that are not a story yet. */
function ResumeIdeas() {
  const resumes = useResumes();
  const main = resumes.data?.find((r) => r.is_main) ?? resumes.data?.[0] ?? null;
  const ideas = useStoryIdeas(main?.id ?? null);
  const client = useQueryClient();
  const dismiss = useMutation({
    mutationFn: (ref: string) => resumesApi.dismissIdea(main?.id ?? "", ref),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.storyIdeas(main?.id ?? "") }),
  });
  if (!main) return null;
  const open = ideas.data?.ideas ?? [];
  const used = ideas.data?.used ?? [];
  return (
    <details className="sx-card coach sx-fold" data-testid="resume-ideas">
      <summary>
        <div className="sx-between">
          <div className="sx-row">
            <Strova mode="coaching" size={28} />
            <h2>Stories recommended from your resume</h2>
          </div>
          <div className="sx-row">
            <span className="sx-small sx-muted">
              {open.length} {open.length === 1 ? "idea" : "ideas"} · {used.length} already a story
            </span>
            <span className="caret" aria-hidden="true">
              ▾
            </span>
          </div>
        </div>
      </summary>
      <p className="sx-small sx-muted">
        Strova found these in your resume's achievements. Build on one with Strova, or dismiss it.
      </p>
      {dismiss.isError && <ErrorNotice error={dismiss.error} />}
      {open.length === 0 && (
        <p className="sx-small sx-muted">
          No more ideas from this resume. Add an achievement on your resume to get new ones.
        </p>
      )}
      {open.map((idea) => (
        <div key={idea.resume_line_ref} className="sx-card tight sx-sugg" role="group" aria-label={idea.achievement}>
          <div className="txt">
            <strong>{idea.achievement}</strong>
            <span className="sx-chips">
              {idea.skills.map((s) => (
                <span key={s} className="sx-chip v">
                  {competencyLabel(s)}
                </span>
              ))}
              {idea.missing_parts.length > 0 && (
                <span className="sx-small sx-muted">Still needs: {idea.missing_parts.join(", ")}</span>
              )}
            </span>
          </div>
          <div className="sx-row">
            <Link className="sx-btn sm" to={craftFromIdeaPath(main.id, idea.resume_line_ref)}>
              Build on it
            </Link>
            <button
              type="button"
              className="sx-btn quiet sm"
              disabled={dismiss.isPending}
              onClick={() => dismiss.mutate(idea.resume_line_ref)}
            >
              Dismiss
            </button>
          </div>
        </div>
      ))}
      {used.map((u) => (
        <div key={u.resume_line_ref} className="sx-between sx-notice ground">
          <span className="sx-small sx-muted">{u.achievement}</span>
          <Link to={storyPath(u.story_id)} className="sx-small career-stories__used">
            Already a story: {u.story_title}
          </Link>
        </div>
      ))}
    </details>
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

/** U08 suggestions for Career Stories (place `stories`). */
function StrovaSuggests() {
  const list = useSuggestions("stories");
  const open = list.data ?? [];
  return (
    <details className="sx-card coach sx-fold" data-testid="strova-suggests">
      <summary>
        <div className="sx-between">
          <div className="sx-row">
            <Strova mode="coaching" size={28} />
            <h2>Strova suggests</h2>
          </div>
          <div className="sx-row">
            <span className="sx-small sx-muted">{open.length} for your stories</span>
            <span className="caret" aria-hidden="true">
              ▾
            </span>
          </div>
        </div>
      </summary>
      {list.isError && <ErrorNotice error={list.error} />}
      {list.data && open.length === 0 && <p className="sx-small sx-muted">Nothing to suggest right now.</p>}
      {open.map((s) => (
        <SuggestRow key={s.id} suggestion={s} />
      ))}
    </details>
  );
}

function SuggestRow({ suggestion }: { suggestion: Suggestion }) {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: suggestionKeys.place("stories") });
    void client.invalidateQueries({ queryKey: ["stories"] });
  };
  const accept = useMutation({ mutationFn: () => suggestionsApi.accept(suggestion.id), onSuccess: refresh });
  const dismiss = useMutation({ mutationFn: () => suggestionsApi.dismiss(suggestion.id), onSuccess: refresh });
  const busy = accept.isPending || dismiss.isPending;
  const p = suggestion.payload;
  let eyebrow: string;
  let tone = "";
  let action: ReactNode;
  switch (p.kind) {
    case "tune_story":
      eyebrow = "Tune a story";
      action = suggestion.story_id && (
        <Link className="sx-btn sm" to={storyPath(suggestion.story_id)}>
          Review
        </Link>
      );
      break;
    case "tailor_role":
      eyebrow = `Tailor for ${p.company}`;
      tone = "teal";
      action = (
        <button type="button" className="sx-btn ghost sm" disabled={busy} onClick={() => accept.mutate()}>
          Add to story
        </button>
      );
      break;
    case "missing_skill":
      eyebrow = `Missing skill · ${competencyLabel(p.competency)}`;
      tone = "warn";
      action = (
        <Link
          className="sx-btn ghost sm"
          to={newCoachPath({ skill: p.competency, job: suggestion.job_target_id ?? undefined })}
        >
          Craft it with Strova
        </Link>
      );
      break;
    case "story_idea":
      eyebrow = "From your resume";
      action = suggestion.resume_id && p.resume_line_ref && (
        <Link className="sx-btn sm" to={craftFromIdeaPath(suggestion.resume_id, p.resume_line_ref)}>
          Build on it
        </Link>
      );
      break;
    default:
      return null;
  }
  return (
    <div className="sx-card tight sx-sugg" role="group" aria-label={eyebrow}>
      <div className="txt">
        <span className={`sx-eyebrow ${tone}`}>{eyebrow}</span>
        <span>{p.kind === "tailor_role" ? p.note : p.kind === "story_idea" ? p.achievement : suggestion.reason}</span>
        {accept.isSuccess && <span className="sx-small" role="status">Added to the story.</span>}
        {(accept.error ?? dismiss.error) && (
          <span className="sx-small" role="alert">
            {(accept.error ?? dismiss.error)?.message}
          </span>
        )}
      </div>
      <div className="sx-row">
        {action}
        <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => dismiss.mutate()}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
