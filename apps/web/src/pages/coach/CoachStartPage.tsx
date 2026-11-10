/**
 * CO-2: `/coach/new?story=&skill=&job=` starts a coach session and replaces itself with the
 * session page. ST-12: `?resume=&idea=` starts from a resume idea (RM-4). Links on Home, the plan's
 * story fit and the workbench open it, so they stay links.
 *
 * SC-1 (UI): a new story is crafted in a style. The page first offers STAR or CARL, with Strova's
 * suggestion for the target skill preselected (D-2, GET /coach/style-suggestion), then starts.
 * `?style=star|carl` starts in that style at once. An existing story starts at once in its own
 * style, and `?style=classic` keeps the five-part session for a new story.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { apiClient, unwrap } from "../../api/client";
import { Strova } from "../../components/strova";
import { ErrorNotice, Eyebrow, Loading } from "../../components/ui";
import { competencyLabel } from "../../labels";
import { storiesPath } from "../stories/paths";
import { coachApi, type StartCoachRequest } from "./api";
import { STYLE_DESCRIPTION, STYLE_NAME, STYLE_SECTIONS, SECTION_LABEL, type StoryStyle } from "./outline";
import { coachPath } from "./paths";
import "./coach.css";

const STYLES: StoryStyle[] = ["star", "carl"];

function baseRequest(params: URLSearchParams): StartCoachRequest {
  return {
    style: "gentle", // switched on the session page (CO-5)
    channel: "text",
    story_id: params.get("story") || null,
    target_skill: (params.get("skill") || null) as StartCoachRequest["target_skill"],
    job_target_id: params.get("job") || null,
    // ST-12: a story idea from the resume (RM-4) seeds the context.
    ...(params.get("resume") && params.get("idea")
      ? { resume_id: params.get("resume"), resume_line_ref: params.get("idea") }
      : {}),
  };
}

const chosenStyle = (value: string | null): StoryStyle | "classic" | null =>
  value === "star" || value === "carl" || value === "classic" ? value : null;

export function CoachStartPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const started = useRef(false);
  const start = useMutation({
    mutationFn: async (body: StartCoachRequest) => {
      const detail = await coachApi.start(body);
      // "Ask Strova" on Home: the question is the candidate's first message.
      const ask = params.get("ask")?.trim();
      if (ask) await coachApi.turn(detail.session.id, ask);
      return detail;
    },
    onSuccess: (detail) => {
      const voice = params.get("voice") === "1" ? "?voice=1" : "";
      navigate(`${coachPath(detail.session.id)}${voice}`, { replace: true });
    },
  });

  const existing = Boolean(params.get("story"));
  const preset = chosenStyle(params.get("style"));
  const pick = !existing && preset === null;

  useEffect(() => {
    if (pick || started.current) return; // StrictMode runs effects twice; start one session
    started.current = true;
    const style = preset === "star" || preset === "carl" ? preset : null;
    start.mutate({ ...baseRequest(params), story_style: existing ? null : style });
  }, [existing, params, pick, preset, start]);

  if (start.isError) {
    return (
      <div className="coach stack">
        <ErrorNotice error={start.error} title="Your session with Strova did not start" />
        <p>
          <Link className="text-link" to={storiesPath}>
            Back to your stories
          </Link>
        </p>
      </div>
    );
  }
  if (!pick || start.isPending || start.isSuccess) {
    return (
      <div className="coach stack">
        <Loading label="Starting your session with Strova" />
      </div>
    );
  }
  return (
    <StylePicker
      skill={params.get("skill")}
      onStart={(style) => start.mutate({ ...baseRequest(params), story_style: style })}
    />
  );
}

function useStyleSuggestion(skill: string | null) {
  return useQuery({
    queryKey: ["coach", "style-suggestion", skill],
    queryFn: async () =>
      unwrap(
        await apiClient.GET("/coach/style-suggestion", {
          params: { query: { target_skill: (skill || undefined) as StartCoachRequest["target_skill"] } },
        }),
      ),
    staleTime: Infinity,
  });
}

/** SC-1 (UI), D-2: STAR or CARL, with Strova's suggestion preselected. */
function StylePicker({ skill, onStart }: { skill: string | null; onStart: (style: StoryStyle) => void }) {
  const suggestion = useStyleSuggestion(skill);
  const suggested = suggestion.data?.style ?? null;
  const [choice, setChoice] = useState<StoryStyle | null>(null);
  const value = choice ?? suggested ?? "star";
  const skillName = skill ? competencyLabel(skill as never).toLowerCase() : null;

  useEffect(() => {
    document.title = "Start a story | Strong Hire";
  }, []);

  return (
    <div className="coach stack coach-start">
      <header className="coach-start__head">
        <Strova mode="coaching" size={56} hat="coach" />
        <div>
          <Eyebrow>Craft with Strova</Eyebrow>
          <h1>How do you want to tell it?</h1>
          <p className="muted">
            Pick a shape for your story. Strova asks about one section at a time, and you can switch later.
          </p>
        </div>
      </header>
      {suggestion.isPending ? (
        <Loading label="Strova is choosing a style" />
      ) : (
        <form
          className="card stack"
          onSubmit={(e) => {
            e.preventDefault();
            onStart(value);
          }}
        >
          <fieldset className="coach-start__styles">
            <legend className="coach-start__legend">Story style</legend>
            {suggested && (
              <p className="muted small" data-testid="style-suggestion">
                Strova suggests {STYLE_NAME[suggested]}
                {skillName ? ` for a ${skillName} story` : ""}.
              </p>
            )}
            <div className="coach-start__options">
              {STYLES.map((style) => (
                <label key={style} className="coach-style" data-checked={value === style || undefined}>
                  <input
                    type="radio"
                    name="story-style"
                    value={style}
                    checked={value === style}
                    onChange={() => setChoice(style)}
                  />
                  <span className="coach-style__name">
                    {STYLE_NAME[style]}
                    {suggested === style && <span className="coach-style__tag">Suggested</span>}
                  </span>
                  <span className="coach-style__sections">
                    {STYLE_SECTIONS[style].map((s) => SECTION_LABEL[s]).join(" · ")}
                  </span>
                  <span className="muted small">{STYLE_DESCRIPTION[style]}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="coach-start__actions">
            <button className="btn" type="submit">
              Start crafting
            </button>
            <Link className="text-link" to={storiesPath}>
              Cancel
            </Link>
          </div>
        </form>
      )}
    </div>
  );
}
