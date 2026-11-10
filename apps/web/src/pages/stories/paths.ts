/** ST-3: the story library and the workbench. */
export const storiesPath = "/stories";

export const storyPath = (id: string) => `/stories/${encodeURIComponent(id)}`;

/** "New story": a manual story, with an optional skill tag already chosen. D-7 (CS-9): from a
 * recommended resume idea, the achievement and its likely skills are prefilled. */
export function newStoryPath(skill?: string, idea?: { text: string; skills?: readonly string[] }) {
  const params = new URLSearchParams();
  for (const s of new Set([...(skill ? [skill] : []), ...(idea?.skills ?? [])])) params.append("skill", s);
  if (idea) params.set("idea", idea.text);
  const query = params.toString();
  return `/stories/new${query ? `?${query}` : ""}`;
}

/** ST-11: Review with Strova for one story. */
export const reviewPath = (id: string) => `/stories/${encodeURIComponent(id)}/review`;
