/**
 * `/stories` is Career Stories with Strova (ST-9, CareerStoriesPage); the studio's list moved
 * there. The status badge, used beside a story elsewhere, shows Draft, Ready or Proven (ST-8).
 */
import { StatusBadge, StoryPartChip } from "../../components/ui";
import { displayStatusLabel, STORY_PARTS, type DisplayStatus } from "./api";

export { CareerStoriesPage as StoriesPage } from "./CareerStoriesPage";

export function StoryStatusBadge({ status }: { status: DisplayStatus }) {
  return <StatusBadge tone={status === "proven" ? "ok" : "neutral"}>{displayStatusLabel[status]}</StatusBadge>;
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
