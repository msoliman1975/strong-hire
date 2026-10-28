/** The story endpoints the debrief uses (S20): the library list (ST-1) and "Save as a story" (ST-2). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiClient, unwrap } from "../../api/client";
import type { components } from "../../api/schema.gen";

export type Story = components["schemas"]["Story"];

export const storiesKey = ["stories"] as const;

export const useStories = () =>
  useQuery({
    queryKey: storiesKey,
    queryFn: async () => unwrap(await apiClient.GET("/stories")) as Story[],
  });

/** ST-2: saves one answer as a Draft story. An answer saved before answers with its story id. */
export function useSaveAsStory(sessionId: string, questionRef: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<string> => {
      try {
        const story = unwrap(
          await apiClient.POST("/stories/from-answer", {
            body: { session_id: sessionId, question_ref: questionRef },
          }),
        ) as Story;
        return story.id;
      } catch (err) {
        if (err instanceof ApiError && err.code === "story_exists" && typeof err.detail?.story_id === "string") {
          return err.detail.story_id;
        }
        throw err;
      }
    },
    onSuccess: () => client.invalidateQueries({ queryKey: storiesKey }),
  });
}

/** The story saved from this answer (ST-2), if there is one. */
export const savedFrom = (stories: Story[], sessionId: string, questionRef: string) =>
  stories.find((s) => s.source_session_id === sessionId && s.source_question_ref === questionRef) ?? null;

export interface LibraryUpdate {
  story: Story;
  kind: "new" | "note";
}

/** The stories this session changed: drafts saved from its answers and stories that got a fix note. */
export function libraryUpdates(stories: Story[], sessionId: string): LibraryUpdate[] {
  const out: LibraryUpdate[] = [];
  for (const story of stories) {
    if (story.source_session_id === sessionId) out.push({ story, kind: "new" });
    else if ((story.notes ?? []).some((n) => n.session_id === sessionId)) out.push({ story, kind: "note" });
  }
  return out;
}
