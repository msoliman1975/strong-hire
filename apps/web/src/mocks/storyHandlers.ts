/**
 * MSW handlers for the story library (ST-1, for ST-3 and ST-4), with the paths, status codes and
 * bodies of apps/api strong_api.stories: newest first, `?status=` and `?skill=` filters, PATCH
 * changes only the fields sent and clears blank parts. The stories live in memory;
 * `resetMockStories` sets them (tests), and the seed gives a click-through something to show.
 */
import { http, HttpResponse } from "msw/http";

import type { Story, StoryAnswer, StoryIn, StoryPatch } from "../pages/stories/api";
import { displayStatusOf, STORY_PARTS } from "../pages/stories/api";
import { requestMockReview } from "./suggestionHandlers";

const API = "*/api";

export function mockStory(changes: Partial<Story> & Pick<Story, "id" | "title">): Story {
  const story: Story = {
    context: null,
    stakes: null,
    action: null,
    result: null,
    reflection: null,
    skills: [],
    status: "draft",
    source: "manual",
    source_session_id: null,
    source_question_ref: null,
    notes: [],
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:00:00Z",
    display_status: "draft",
    ...changes,
  };
  return out(story);
}

/** ST-8: the status to show, as the API computes it on every response. */
function out(story: Story): Story {
  return { ...story, display_status: displayStatusOf(story) };
}

const SEED: Story[] = [
  mockStory({
    id: "11111111-1111-4111-8111-111111111111",
    title: "Checkout migration",
    context: "Our checkout ran on a payments service three teams depended on, and no one owned the migration off it.",
    stakes: "About 2 percent of checkouts failed every week.",
    action: "I wrote the migration plan, got the three team leads to agree on a phased rollout, and ran a weekly review of error rates.",
    result: "Checkout errors dropped 40 percent in six weeks.",
    skills: ["ownership", "impact", "collaboration"],
    status: "proven",
    source: "debrief_answer",
    notes: [
      { text: "Say the 40 percent first, then how you got there.", at: "2026-10-22T09:00:00Z", session_id: null, question_ref: null },
    ],
    created_at: "2026-10-18T10:00:00Z",
  }),
  mockStory({
    id: "22222222-2222-4222-8222-222222222222",
    title: "Pushback from platform",
    context: "The platform team refused to change an API my team needed.",
    skills: ["conflict_handling"],
    created_at: "2026-10-21T10:00:00Z",
  }),
];

let stories: Story[] = structuredClone(SEED);

/** Sets the mock library. No argument: the seed. */
export function resetMockStories(next: Story[] = SEED) {
  stories = structuredClone(next);
}

/** The live mock library, for other mocks that write stories (coachHandlers.ts, S31). */
export const mockStoryLibrary = () => stories;

const clean = (text: string | null | undefined) => (text ?? "").trim() || null;

function notFound() {
  return HttpResponse.json({ detail: "Story not found" }, { status: 404 });
}

export function storyHandlers() {
  return [
    http.get(`${API}/stories`, ({ request }) => {
      const url = new URL(request.url);
      const status = url.searchParams.get("status");
      const skill = url.searchParams.get("skill");
      const list = stories
        .filter((s) => !status || s.status === status)
        .filter((s) => !skill || (s.skills as string[]).includes(skill))
        .sort((a, b) => b.created_at.localeCompare(a.created_at));
      return HttpResponse.json(list.map(out));
    }),

    http.post(`${API}/stories`, async ({ request }) => {
      const body = (await request.json()) as StoryIn;
      if (!body.title?.trim()) {
        return HttpResponse.json({ detail: [{ msg: "A story needs a title" }] }, { status: 422 });
      }
      const now = new Date().toISOString();
      const story = mockStory({
        id: crypto.randomUUID(),
        title: body.title.trim(),
        ...Object.fromEntries(STORY_PARTS.map((p) => [p, clean(body[p])])),
        skills: body.skills ?? [],
        source: body.source ?? "manual",
        created_at: now,
        updated_at: now,
      });
      stories.push(story);
      return HttpResponse.json(out(story), { status: 201 });
    }),

    http.get(`${API}/stories/:id`, ({ params }) => {
      const story = stories.find((s) => s.id === params.id);
      return story ? HttpResponse.json(out(story)) : notFound();
    }),

    http.patch(`${API}/stories/:id`, async ({ params, request }) => {
      const story = stories.find((s) => s.id === params.id);
      if (!story) return notFound();
      const body = (await request.json()) as StoryPatch;
      if ("title" in body) {
        if (!clean(body.title)) {
          return HttpResponse.json({ detail: [{ msg: "A story needs a title" }] }, { status: 422 });
        }
        story.title = (body.title as string).trim();
      }
      for (const p of STORY_PARTS) if (p in body) story[p] = clean(body[p]);
      if ("skills" in body) story.skills = body.skills ?? [];
      story.updated_at = new Date().toISOString();
      return HttpResponse.json(out(story));
    }),

    // ST-11: the review arrives as an open review suggestion for the story (suggestionHandlers).
    http.post(`${API}/stories/:id/review`, ({ params }) => {
      const story = stories.find((s) => s.id === params.id);
      if (!story) return notFound();
      requestMockReview(story.id);
      return HttpResponse.json({ job_id: `review_story:${story.id}` }, { status: 202 });
    }),

    // ST-13: an answer from the first story with a result, quoting it.
    http.post(`${API}/stories/ask`, async ({ request }) => {
      const { question } = (await request.json()) as { question: string };
      if (!question?.trim()) return HttpResponse.json({ detail: [{ msg: "Ask a question" }] }, { status: 422 });
      const lead = stories.find((s) => s.result?.trim());
      const answer: StoryAnswer = lead
        ? {
            answer: `Lead with “${lead.title}”. Say the result first: ${lead.result}`,
            story_ids: [lead.id],
            quotes: [lead.result as string],
          }
        : {
            answer: "I can't answer that from your stories yet. Add a story that shows it, and ask me again.",
            story_ids: [],
            quotes: [],
          };
      return HttpResponse.json(answer);
    }),
  ];
}
