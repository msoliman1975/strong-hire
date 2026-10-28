import type { Story } from "./api";

/**
 * Slot for S31 on the workbench's right column: the story's takes and versions. Empty until S31
 * fills it; S31 edits this file. The takes and versions endpoints are /stories/{id}/takes and
 * /stories/{id}/versions.
 */
export function StoryTakes({ story }: { story: Story }) {
  void story;
  return (
    <section className="card" aria-labelledby="story-takes-heading" data-testid="story-takes">
      <h2 id="story-takes-heading">Takes and versions</h2>
      <p className="muted">Practice this story with your coach, and each take and version shows here.</p>
    </section>
  );
}
