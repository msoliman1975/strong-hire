/**
 * ST-4 on Home (canvas board Home): the newest stories as cards, and the skill coverage map below
 * them. The counts sit on the journey A card above (HomeV2).
 */
import "./StoryLibrary.css";

import { Link } from "react-router";

import { competencyLabel } from "../../labels";
import { ErrorNotice } from "../../components/ui";
import { filledParts, useStories, type Story } from "../stories/api";
import { newCoachPath } from "../coach/paths";
import { newStoryPath, storiesPath, storyPath } from "../stories/paths";
import { PartsDone, StoryStatusBadge } from "../stories/StoriesPage";
import { SkillCoverage } from "./SkillCoverage";

const SHOWN = 4;

export function StoryLibrary() {
  const stories = useStories();
  if (stories.isPending) return null;
  if (stories.isError) return <ErrorNotice error={stories.error} title="Your stories did not load" />;
  const all = stories.data;
  return (
    <>
      <section className="home-stories" aria-labelledby="home-stories-heading">
        <div className="home-section__head">
          <h2 id="home-stories-heading">Your story library</h2>
          {all.length > 0 && (
            <Link className="text-link" to={storiesPath}>
              All {all.length} {all.length === 1 ? "story" : "stories"}
            </Link>
          )}
        </div>
        {all.length === 0 ? (
          <div className="card home-stories__empty">
            <p className="muted">Save an answer from a debrief, or tell your coach about work you are proud of.</p>
            <div className="stories__actions">
              <Link className="btn" to={newCoachPath()}>
                Build a story
              </Link>
              <Link className="btn btn--secondary" to={newStoryPath()}>
                Write one yourself
              </Link>
            </div>
          </div>
        ) : (
          <ul className="plain-list home-stories__list" aria-label="Newest stories">
            {all.slice(0, SHOWN).map((s) => (
              <StoryCard key={s.id} story={s} />
            ))}
          </ul>
        )}
      </section>
      <SkillCoverage stories={all} />
    </>
  );
}

function StoryCard({ story }: { story: Story }) {
  return (
    <li className="card home-story" data-testid="home-story">
      <div className="home-story__top">
        <Link className="home-story__title" to={storyPath(story.id)}>
          {story.title}
        </Link>
        <StoryStatusBadge status={story.status} />
      </div>
      <PartsDone filled={filledParts(story)} />
      <p className="muted small">
        {story.skills.length > 0 ? `Proves: ${story.skills.map(competencyLabel).join(", ")}` : "No skill tags yet"}
      </p>
    </li>
  );
}
