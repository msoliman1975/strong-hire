/**
 * ST-3: the story studio (canvas board A2 Workbench), two panes. Left: the library, with search,
 * the status filter (All, Proven, Needs work) and a skill filter; status and skill live in the URL
 * (`?status=`, `?skill=`) and go to the API. Right: the selected story (StoryView). `/stories`
 * shows the first story beside the list; `/stories/:storyId` shows that one. Below 900px only one
 * pane shows: the list on `/stories`, the story on `/stories/:storyId`.
 */
import "./stories.css";

import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { COMPETENCIES_BY_TYPE } from "../../api/questions";
import { competencyLabel } from "../../labels";
import { ErrorNotice, Loading, PageHead, Segmented, StatusBadge, StoryPartChip } from "../../components/ui";
import { newCoachPath } from "../coach/paths";
import { filledParts, STORY_PARTS, storyStatusLabel, useStories, type Competency, type Story, type StoryStatus } from "./api";
import { newStoryPath, storiesPath, storyPath } from "./paths";
import { StoryView } from "./StoryView";

/** Every competency once, in the order of COMPETENCIES_BY_TYPE. The recruiter screen repeats three. */
export const SKILLS = [...new Set(Object.values(COMPETENCIES_BY_TYPE).flat())] as Competency[];
const STATUSES: StoryStatus[] = ["proven", "draft"];

type StatusChoice = StoryStatus | "all";

export function StoriesPage() {
  const { storyId } = useParams();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const statusParam = params.get("status");
  const status = STATUSES.find((s) => s === statusParam);
  const skillParam = params.get("skill");
  const skill = SKILLS.find((s) => s === skillParam);
  const stories = useStories({ status, skill });
  const all = useStories();

  const setFilter = (key: "status" | "skill", value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const filtered = status !== undefined || skill !== undefined || search.trim() !== "";
  const needle = search.trim().toLowerCase();
  const shown = (stories.data ?? []).filter((s) => needle === "" || s.title.toLowerCase().includes(needle));
  const selected = storyId ?? shown[0]?.id ?? null;
  const query = params.toString();

  return (
    <div className="stories studio" data-selected={storyId ? "true" : "false"}>
      <PageHead title="Your stories" eyebrow="Story studio">
        <div className="stories__actions">
          <Link className="btn btn--secondary" to={newCoachPath()}>
            New story with the coach
          </Link>
          <Link className="btn btn--quiet" to={newStoryPath()}>
            Write one yourself
          </Link>
        </div>
      </PageHead>

      <div className="studio__panes">
        <nav className="card studio__library" aria-label="Story library">
          <div className="studio__filters" role="search" aria-label="Filter stories">
            <label htmlFor="studio-search" className="visually-hidden">
              Search stories
            </label>
            <input
              id="studio-search"
              type="search"
              placeholder="Search stories"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Segmented<StatusChoice>
              label="Status"
              value={status ?? "all"}
              onChange={(v) => setFilter("status", v === "all" ? undefined : v)}
              options={[
                { value: "all", label: all.data ? `All ${all.data.length}` : "All" },
                { value: "proven", label: "Proven" },
                // A Draft is a story that still needs work: it is not yet proven (ST-7).
                { value: "draft", label: "Needs work" },
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
            (shown.length === 0 ? (
              filtered ? (
                <p className="muted studio__empty">No stories match these filters.</p>
              ) : (
                /* R3: an empty page teaches what it is for, and gives the one button to start. */
                <div className="studio__empty studio__teach" data-testid="stories-empty">
                  <b>No stories yet</b>
                  <p className="muted">
                    A story is one moment from your career, told in 5 parts, ready for "tell me about a time…"
                    questions. Your coach builds the first one with you, from your own words.
                  </p>
                  <Link className="btn" to={newCoachPath()}>
                    Build my first story
                  </Link>
                </div>
              )
            ) : (
              <ul className="plain-list studio__list" aria-label="Stories">
                {shown.map((s) => (
                  <StoryRow key={s.id} story={s} current={s.id === selected} query={query} />
                ))}
              </ul>
            ))}
        </nav>

        <div className="studio__story">
          {storyId && (
            <p className="studio__back">
              <Link className="text-link" to={`${storiesPath}${query ? `?${query}` : ""}`}>
                All stories
              </Link>
            </p>
          )}
          {selected ? (
            <StoryView key={selected} storyId={selected} />
          ) : (
            stories.data && (
              <div className="card studio__none">
                <p className="muted">Your stories show here, each with its versions, takes and coach notes.</p>
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}

function StoryRow({ story, current, query }: { story: Story; current: boolean; query: string }) {
  const filled = filledParts(story).length;
  return (
    <li data-testid="story-row">
      <Link
        className="studio__row"
        to={`${storyPath(story.id)}${query ? `?${query}` : ""}`}
        aria-current={current ? "page" : undefined}
      >
        <span className="studio__row-title">{story.title}</span>
        <span className="studio__row-meta">
          {storyStatusLabel[story.status]}
          {story.status === "draft" && ` · ${filled} of 5 parts`}
          {story.skills.length > 0 && <> · {story.skills.map(competencyLabel).join(", ")}</>}
        </span>
      </Link>
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
