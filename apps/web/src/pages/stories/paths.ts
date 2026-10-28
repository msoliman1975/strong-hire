/** ST-3: the story library and the workbench. */
export const storiesPath = "/stories";

export const storyPath = (id: string) => `/stories/${encodeURIComponent(id)}`;

/** "New story": a manual story, with an optional skill tag already chosen. */
export const newStoryPath = (skill?: string) => `/stories/new${skill ? `?skill=${encodeURIComponent(skill)}` : ""}`;
