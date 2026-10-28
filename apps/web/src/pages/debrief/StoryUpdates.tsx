import { Link } from "react-router";

import { storyPath } from "../plan/StoryFitTable";
import { libraryUpdates, useStories } from "./StoryApi";

/**
 * ST-6, ST-2: the debrief's summary card, "N updates for your library": the stories that got a
 * fix note from this session and the drafts saved from its answers. Hidden when there are none.
 */
export function StoryUpdates({ sessionId }: { sessionId: string }) {
  const stories = useStories();
  const updates = libraryUpdates(stories.data ?? [], sessionId);
  if (updates.length === 0) return null;
  return (
    <section className="card debrief-story-updates" aria-labelledby="debrief-story-updates-heading">
      <h2 id="debrief-story-updates-heading">
        {updates.length} {updates.length === 1 ? "update" : "updates"} for your library
      </h2>
      <ul className="plain-list">
        {updates.map(({ story, kind }) => (
          <li key={story.id}>
            <Link to={storyPath(story.id)}>{story.title}</Link>{" "}
            <span className="muted small">{kind === "new" ? "New draft from this debrief" : "Fix note added"}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
