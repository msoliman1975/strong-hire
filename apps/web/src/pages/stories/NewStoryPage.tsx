/**
 * ST-10 (mockup #write): Write it yourself. A title and the five parts, each with its hint. Save
 * as a Draft goes back to Career Stories; Save and ask Strova to review saves, queues the review
 * (ST-11) and opens Review with Strova. `?skill=` tags the story first (Home coverage, plan gaps);
 * it may repeat. D-7 (CS-9): `?idea=` is a recommended resume achievement: it names the story and
 * fills the result, in the user's own words from their resume.
 *
 * SC-1, SC-10: the story can be written in STAR or CARL (STAR is preselected): the outline's
 * sections and slots, in the user's own words, saved as typed with no model call. "Five free-text
 * parts" keeps the classic form.
 */
import "../../components/ux/ux.css";
import "../coach/coach.css";
import "./stories.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { Strova } from "../../components/strova";
import { ErrorNotice, STORY_PART_LABEL } from "../../components/ui";
import { STYLE_DESCRIPTION, STYLE_NAME, STYLE_SECTIONS, SECTION_LABEL, type StoryStyle } from "../coach/outline";
import { SKILLS, STORY_PARTS, storiesApi, storyKeys, type Competency } from "./api";
import { WriteOutline, writtenSlots, type Written } from "./WriteOutline";
import { reviewPath, storiesPath } from "./paths";

export const PART_HINT: Record<(typeof STORY_PARTS)[number], string> = {
  context: "Where you were and what was going on",
  stakes: "Why it mattered, and what could go wrong",
  action: "What you did yourself, and the trade-offs",
  result: "What changed, with a number if you have one",
  reflection: "What you learned, or would do differently",
};

type Parts = Record<(typeof STORY_PARTS)[number], string>;
type Shape = StoryStyle | "classic";

const SHAPES: { value: Shape; name: string; sections: string; description: string }[] = [
  ...(["star", "carl"] as StoryStyle[]).map((s) => ({
    value: s,
    name: STYLE_NAME[s],
    sections: STYLE_SECTIONS[s].map((x) => SECTION_LABEL[x]).join(" · "),
    description: STYLE_DESCRIPTION[s],
  })),
  {
    value: "classic",
    name: "Five free-text parts",
    sections: "One box each for context, stakes, action, result and reflection",
    description: "As before. You can organize it into STAR later.",
  },
];

/** D-7: a story started from a resume line is first named after it. */
export function titleFromIdea(idea: string): string {
  const line = idea.trim().replace(/[.;]+$/, "");
  return line.length <= 80 ? line : `${line.slice(0, 79).trimEnd()}…`;
}

export function NewStoryPage() {
  const [params] = useSearchParams();
  const skills: Competency[] = [...new Set(params.getAll("skill"))].filter((s): s is Competency =>
    SKILLS.includes(s as Competency),
  );
  const idea = params.get("idea")?.trim() ?? "";
  const [title, setTitle] = useState(() => (idea ? titleFromIdea(idea) : ""));
  const [parts, setParts] = useState<Parts>({ context: "", stakes: "", action: "", result: idea, reflection: "" });
  const [missing, setMissing] = useState(false);
  const [shape, setShape] = useState<Shape>("star");
  const [written, setWritten] = useState<Written>(() => (idea ? { "result.impact": idea } : ({} as Written)));
  const [steps, setSteps] = useState(1);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: async (review: boolean) => {
      const story = await storiesApi.create(
        shape === "classic"
          ? {
              title: title.trim(),
              ...Object.fromEntries(STORY_PARTS.map((p) => [p, parts[p].trim() || null])),
              skills,
              source: "manual",
            }
          : { title: title.trim(), skills, source: "manual", style: shape, slots: writtenSlots(shape, written, steps) },
      );
      if (review) await storiesApi.review(story.id);
      return { story, review };
    },
    onSuccess: ({ story, review }) => {
      void queryClient.invalidateQueries({ queryKey: storyKeys.all });
      navigate(review ? reviewPath(story.id) : storiesPath, { replace: true });
    },
  });

  const submit = (review: boolean) => {
    if (title.trim() === "") {
      setMissing(true);
      return;
    }
    save.mutate(review);
  };

  return (
    <div className="sx-page sx-page--narrow">
      <Link to={storiesPath} className="sx-small">
        Career Stories with Strova
      </Link>
      <div className="sx-stack">
        <div className="sx-eyebrow plain">Write it yourself</div>
        <h1>New story</h1>
        <p className="sx-small sx-muted">
          Write it in your own words. You can leave parts empty and come back; nothing is added that you didn't write.
        </p>
        {idea && (
          <p className="sx-small" data-testid="from-idea">
            From your resume: <q>{idea}</q>. It's in the result; add what led to it.
          </p>
        )}
      </div>
      <form className="sx-card" aria-label="Write a story" onSubmit={(e) => e.preventDefault()} noValidate>
        <div className="sx-field">
          <label htmlFor="write-title">Story title</label>
          <input
            id="write-title"
            value={title}
            maxLength={200}
            placeholder="For example: Pushback from platform"
            aria-invalid={missing || undefined}
            aria-describedby={missing ? "write-title-error" : undefined}
            onChange={(e) => {
              setTitle(e.target.value);
              setMissing(false);
            }}
          />
          {missing && (
            <span id="write-title-error" className="sx-small" role="alert">
              Give the story a title.
            </span>
          )}
        </div>
        <fieldset className="coach-start__styles write-shape">
          <legend className="coach-start__legend">Story shape</legend>
          <div className="coach-start__options">
            {SHAPES.map((o) => (
              <label key={o.value} className="coach-style" data-checked={shape === o.value || undefined}>
                <input type="radio" name="story-shape" value={o.value} checked={shape === o.value} onChange={() => setShape(o.value)} />
                <span className="coach-style__name">{o.name}</span>
                <span className="coach-style__sections">{o.sections}</span>
                <span className="muted small">{o.description}</span>
              </label>
            ))}
          </div>
        </fieldset>
        {shape !== "classic" && (
          <WriteOutline style={shape} values={written} onChange={setWritten} steps={steps} onSteps={setSteps} />
        )}
        {shape === "classic" && STORY_PARTS.map((p) => (
          <div key={p} className="sx-field">
            <label htmlFor={`write-${p}`} className="write-part" data-part={p}>
              ● {STORY_PART_LABEL[p]}
            </label>
            <textarea
              id={`write-${p}`}
              rows={2}
              value={parts[p]}
              placeholder={PART_HINT[p]}
              onChange={(e) => setParts({ ...parts, [p]: e.target.value })}
            />
          </div>
        ))}
        <div className="sx-notice v sx-small sx-row">
          <Strova mode="coaching" size={20} />
          <span>
            <strong>Want a second pair of eyes?</strong> Strova reviews each part against what interviewers look for,
            and suggests edits in your own words for you to accept or skip.
          </span>
        </div>
        {save.isError && <ErrorNotice error={save.error} />}
        <div className="sx-row">
          <button type="button" className="sx-btn" disabled={save.isPending} onClick={() => submit(true)}>
            Save and ask Strova to review
          </button>
          <button type="button" className="sx-btn ghost" disabled={save.isPending} onClick={() => submit(false)}>
            Save as a Draft
          </button>
        </div>
      </form>
    </div>
  );
}
