/**
 * ST-4 on Home (canvas board Home): the story library, with counts and the newest stories, and
 * the skill coverage map below it. HomeV2 renders this below the interview cards.
 */
import "./StoryLibrary.css";

import { Link } from "react-router";

import { competencyLabel } from "../../labels";
import { ErrorNotice, Eyebrow } from "../../components/ui";
import { filledParts, useStories, type Story } from "../stories/api";
import { newStoryPath, storiesPath, storyPath } from "../stories/paths";
import { PartsDone, StoryStatusBadge } from "../stories/StoriesPage";
import { SkillCoverage } from "./SkillCoverage";

const SHOWN = 4;

export function StoryLibrary() {
  const stories = useStories();
  if (stories.isPending) return null;
  if (stories.isError) return <ErrorNotice error={stories.error} title="Your stories did not load" />;
  const all = stories.data;
  const proven = all.filter((s) => s.status === "proven").length;
  return (
    <>
      <section className="card card--action home-stories" aria-labelledby="home-stories-heading">
        <Eyebrow>A · Build your stories</Eyebrow>
        <div className="home-section__head">
          <h2 id="home-stories-heading">Your story library</h2>
          {all.length > 0 && (
            <Link className="text-link" to={storiesPath}>
              All {all.length} {all.length === 1 ? "story" : "stories"}
            </Link>
          )}
        </div>
        <dl className="home-stories__counts">
          <div>
            <dt>Stories</dt>
            <dd>{all.length}</dd>
          </div>
          <div>
            <dt>Proven</dt>
            <dd data-tone="ok">{proven}</dd>
          </div>
          <div>
            <dt>Drafts</dt>
            <dd>{all.length - proven}</dd>
          </div>
        </dl>
        {all.length === 0 ? (
          <p className="muted">Save an answer from a debrief, or write a story about work you are proud of.</p>
        ) : (
          <ul className="plain-list home-stories__list" aria-label="Newest stories">
            {all.slice(0, SHOWN).map((s) => (
              <StoryCard key={s.id} story={s} />
            ))}
          </ul>
        )}
        <div>
          <Link className="btn btn--secondary" to={newStoryPath()}>
            New story
          </Link>
        </div>
      </section>
      <SkillCoverage stories={all} />
    </>
  );
}

function StoryCard({ story }: { story: Story }) {
  return (
    <li className="card card--soft home-story" data-testid="home-story">
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
