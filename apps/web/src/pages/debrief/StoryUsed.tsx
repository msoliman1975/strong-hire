import type { QuestionScore } from "../../api/types";

/**
 * ST-6 slot for S23: the story an answer used and where its fix went. Empty until S23 fills it;
 * S23 edits this file only. `answer.story_id` and `answer.story_fix` come from the scorecard.
 */
export function StoryUsed({ answer }: { answer: QuestionScore }) {
  void answer;
  return null;
}
