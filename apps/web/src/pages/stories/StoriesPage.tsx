/**
 * ST-3: the story library (canvas board A2 Workbench, left column). Filters by status and skill
 * live in the URL (`?status=`, `?skill=`) and go to the API, which does the filtering.
 */
import "./stories.css";

import { Link, useSearchParams } from "react-router";

import { COMPETENCIES_BY_TYPE } from "../../api/questions";
import { competencyLabel } from "../../labels";
import { ErrorNotice, Loading, PageHead, Pill, Segmented, StatusBadge, StoryPartChip } from "../../components/ui";
import { filledParts, STORY_PARTS, storyStatusLabel, useStories, type Competency, type Story, type StoryStatus } from "./api";
import { newStoryPath, storyPath } from "./paths";

const SKILLS = Object.values(COMPETENCIES_BY_TYPE).flat() as Competency[];
const STATUSES: StoryStatus[] = ["proven", "draft"];

type StatusChoice = StoryStatus | "all";

export function StoriesPage() {
  const [params, setParams] = useSearchParams();
  const statusParam = params.get("status");
  const status = STATUSES.find((s) => s === statusParam);
  const skillParam = params.get("skill");
  const skill = SKILLS.find((s) => s === skillParam);
  const stories = useStories({ status, skill });

  const setFilter = (key: "status" | "skill", value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const filtered = status !== undefined || skill !== undefined;

  return (
    <div className="stories stack">
      <PageHead title="Your stories" eyebrow="A · Story studio">
        <Link className="btn" to={newStoryPath()}>
          New story
        </Link>
      </PageHead>

      <div className="stories__filters" role="search" aria-label="Filter stories">
        <Segmented<StatusChoice>
          label="Status"
          value={status ?? "all"}
          onChange={(v) => setFilter("status", v === "all" ? undefined : v)}
          options={[
            { value: "all", label: "All" },
            { value: "proven", label: "Proven" },
            { value: "draft", label: "Draft" },
          ]}
        />
        <label className="stories__skill-filter">
          <span className="label">Skill</span>
          <select value={skill ?? ""} onChange={(e) => setFilter("skill", e.target.value || undefined)}>
            <option value="">All skills</option>
            {SKILLS.map((c) => (
              <option key={c} value={c}>
                {competencyLabel(c)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {stories.isPending && <Loading label="Loading your stories" />}
      {stories.isError && <ErrorNotice error={stories.error} />}
      {stories.data &&
        (stories.data.length === 0 ? (
          <div className="card card--soft">
            <p>{filtered ? "No stories match these filters." : "No stories yet. Save one from a debrief, or write one here."}</p>
          </div>
        ) : (
          <ul className="plain-list stories__list" aria-label="Stories">
            {stories.data.map((s) => (
              <StoryRow key={s.id} story={s} />
            ))}
          </ul>
        ))}
    </div>
  );
}

function StoryRow({ story }: { story: Story }) {
  const filled = filledParts(story);
  return (
    <li className="card story-row" data-testid="story-row">
      <div className="story-row__top">
        <Link className="story-row__title" to={storyPath(story.id)}>
          {story.title}
        </Link>
        <StoryStatusBadge status={story.status} />
      </div>
      {story.skills.length > 0 ? (
        <ul className="plain-list chip-list" aria-label="Skills">
          {story.skills.map((c) => (
            <li key={c}>
              <Pill>{competencyLabel(c)}</Pill>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">No skill tags yet</p>
      )}
      <PartsDone filled={filled} />
    </li>
  );
}

export function StoryStatusBadge({ status }: { status: StoryStatus }) {
  return <StatusBadge tone={status === "proven" ? "ok" : "neutral"}>{storyStatusLabel[status]}</StatusBadge>;
}

/** Which of the five parts have text. Each chip names its part, so color is never the only cue. */
export function PartsDone({ filled }: { filled: readonly string[] }) {
  return (
    <p className="story-parts-done">
      <span className="visually-hidden">
        {filled.length} of 5 parts written{filled.length > 0 ? `: ${filled.join(", ")}` : ""}.
      </span>
      <span className="story-parts-done__chips" aria-hidden="true">
        {STORY_PARTS.map((p) => (
          <StoryPartChip key={p} part={p} state={filled.includes(p) ? "done" : "next"} />
        ))}
      </span>
    </p>
  );
}
