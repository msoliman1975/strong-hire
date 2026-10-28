/**
 * ST-3 on the v2 Progress page: the stories that need work, each with why and a link to work on
 * it with the coach. A story needs work when it is a Draft, has a part not written yet, or has
 * coach notes from debriefs. From GET /stories only.
 */
import { Link } from "react-router";

import { ErrorNotice, STORY_PART_LABEL } from "../../components/ui";
import { newCoachPath } from "../coach/paths";
import { STORY_PARTS, filledParts, useStories, type Story } from "../stories/api";
import { storiesPath, storyPath } from "../stories/paths";
import { StoryStatusBadge } from "../stories/StoriesPage";

/** Why a story needs work, in words; empty when it does not. */
export function workReasons(story: Story): string[] {
  const reasons: string[] = [];
  if (story.status === "draft") reasons.push("Not proven yet");
  const filled = filledParts(story);
  const missing = STORY_PARTS.filter((p) => !filled.includes(p));
  if (missing.length > 0) reasons.push(`Missing ${missing.map((p) => STORY_PART_LABEL[p].toLowerCase()).join(", ")}`);
  if (story.notes.length > 0) {
    reasons.push(`${story.notes.length} coach ${story.notes.length === 1 ? "note" : "notes"}`);
  }
  return reasons;
}

export function StoriesToWorkOn() {
  const stories = useStories();
  if (stories.isPending) return null;
  if (stories.isError) return <ErrorNotice error={stories.error} title="Your stories did not load" />;
  const todo = stories.data.filter((s) => workReasons(s).length > 0);
  return (
    <section className="card progress-stories" aria-labelledby="progress-stories-heading">
      <div className="home-section__head">
        <h2 id="progress-stories-heading">Stories to work on</h2>
        <Link className="text-link" to={storiesPath}>
          All stories
        </Link>
      </div>
      {todo.length === 0 ? (
        <p className="muted">
          {stories.data.length === 0
            ? "No stories yet. Build your first one with your coach."
            : "Every story is proven, complete and has no open coach notes."}
        </p>
      ) : (
        <ul className="plain-list progress-stories__list" aria-label="Stories that need work">
          {todo.map((s) => (
            <li key={s.id} className="progress-story" data-testid="story-to-work-on">
              <div className="progress-story__main">
                <Link className="progress-story__title" to={storyPath(s.id)}>
                  {s.title}
                </Link>
                <StoryStatusBadge status={s.status} />
                <p className="muted small">{workReasons(s).join(" · ")}</p>
              </div>
              <Link className="btn btn--secondary" to={newCoachPath({ story: s.id })}>
                Work on it
              </Link>
            </li>
          ))}
        </ul>
      )}
      {stories.data.length === 0 && (
        <div>
          <Link className="btn" to={newCoachPath()}>
            Build a story
          </Link>
        </div>
      )}
    </section>
  );
}
