/**
 * ST-10 (mockup #write): Write it yourself. A title and the five parts, each with its hint. Save
 * as a Draft goes back to Career Stories; Save and ask Strova to review saves, queues the review
 * (ST-11) and opens Review with Strova. `?skill=` tags the story first (Home coverage, plan gaps).
 */
import "../../components/ux/ux.css";
import "./stories.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { Strova } from "../../components/strova";
import { ErrorNotice, STORY_PART_LABEL } from "../../components/ui";
import { SKILLS, STORY_PARTS, storiesApi, storyKeys, type Competency } from "./api";
import { reviewPath, storiesPath } from "./paths";

export const PART_HINT: Record<(typeof STORY_PARTS)[number], string> = {
  context: "Where you were and what was going on",
  stakes: "Why it mattered, and what could go wrong",
  action: "What you did yourself, and the trade-offs",
  result: "What changed, with a number if you have one",
  reflection: "What you learned, or would do differently",
};

type Parts = Record<(typeof STORY_PARTS)[number], string>;

export function NewStoryPage() {
  const [params] = useSearchParams();
  const first = SKILLS.find((c) => c === params.get("skill"));
  const skills: Competency[] = first ? [first] : [];
  const [title, setTitle] = useState("");
  const [parts, setParts] = useState<Parts>({ context: "", stakes: "", action: "", result: "", reflection: "" });
  const [missing, setMissing] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: async (review: boolean) => {
      const story = await storiesApi.create({
        title: title.trim(),
        ...Object.fromEntries(STORY_PARTS.map((p) => [p, parts[p].trim() || null])),
        skills,
        source: "manual",
      });
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
        <p className="sx-small sx-muted">Write each part in your own words. You can leave parts empty and come back.</p>
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
        {STORY_PARTS.map((p) => (
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
