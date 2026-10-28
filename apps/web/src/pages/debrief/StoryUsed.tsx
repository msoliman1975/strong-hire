import { Link, useParams } from "react-router";

import type { QuestionScore } from "../../api/types";
import { storyPath } from "../plan/StoryFitTable";
import { savedFrom, useSaveAsStory, useStories } from "./StoryApi";

/**
 * ST-6: the story an answer used, linking to the workbench, and its fix "Sent to story" (the
 * scorer already added it to the story as a note). ST-2: with no story matched, "Save as a story"
 * makes a Draft story from the answer. `answer.story_id` and `answer.story_fix` come from the
 * scorecard.
 */
export function StoryUsed({ answer }: { answer: QuestionScore }) {
  const { sessionId = "" } = useParams();
  const stories = useStories();
  const library = stories.data ?? [];

  if (answer.story_id) {
    const story = library.find((s) => s.id === answer.story_id);
    return (
      <div className="debrief-story" data-testid="story-used">
        <p>
          <b>Story used:</b>{" "}
          {story ? <Link to={storyPath(story.id)}>{story.title}</Link> : stories.isPending ? "…" : "a story since deleted"}
        </p>
        {answer.story_fix && (
          <p>
            <b>Story fix:</b> {answer.story_fix} <span className="debrief-story__sent">Sent to story</span>
          </p>
        )}
      </div>
    );
  }

  const saved = savedFrom(library, sessionId, answer.question_ref);
  return (
    <div className="debrief-story" data-testid="story-used">
      <p>
        <b>No story matched.</b>{" "}
        {saved ? (
          <>
            Saved as <Link to={storyPath(saved.id)}>{saved.title}</Link>.
          </>
        ) : (
          sessionId && <SaveAsStory sessionId={sessionId} questionRef={answer.question_ref} />
        )}
      </p>
    </div>
  );
}

function SaveAsStory({ sessionId, questionRef }: { sessionId: string; questionRef: string }) {
  const save = useSaveAsStory(sessionId, questionRef);
  if (save.isSuccess) {
    return (
      <>
        Saved. <Link to={storyPath(save.data)}>Open the story</Link>.
      </>
    );
  }
  return (
    <>
      <button type="button" className="btn btn--quiet" disabled={save.isPending} onClick={() => save.mutate()}>
        {save.isPending ? "Saving…" : "Save as a story"}
      </button>
      {save.isError && (
        <span className="muted small" role="alert">
          {" "}
          {save.error.message}
        </span>
      )}
    </>
  );
}
