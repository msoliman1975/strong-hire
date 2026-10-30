/**
 * MSW handlers for the coach (CO-2 to CO-5), takes (CO-7) and versions (CO-8), with the paths,
 * status codes and bodies of apps/api strong_api.coach and strong_api.takes. The coach is
 * scripted: each candidate turn fills the part it asks for with the candidate's own words. Coach
 * stories are written to the story mock's library, so the workbench opens them.
 *
 * `resetMockCoach` clears sessions and takes (tests); `scriptMockCoach` sets the next replies.
 */
import { http, HttpResponse } from "msw/http";

import type {
  AskFor,
  CoachSessionDetail,
  CoachSessionOut,
  CoachStyle,
  CoachTurnOut,
  CoachTurnResult,
  StartCoachRequest,
  StoryPart,
  StoryVersions,
  TakeOut,
  TakeRequest,
} from "../pages/coach/api";
import { STORY_PARTS, type Competency, type Story } from "../pages/stories/api";
import type { MockStore } from "./db";
import { mockStory, mockStoryLibrary } from "./storyHandlers";

/** ST-12: the resume achievement a story idea (RM-4) starts from, as the API reads it. */
function ideaLine(store: MockStore | undefined, resumeId: string, ref: string): string | null {
  const found = /^roles\[(\d+)\]\.achievements\[(\d+)\]$/.exec(ref);
  const resume = store?.db.resumes.find((r) => r.id === resumeId)?.resume;
  if (!found || !resume) return null;
  return resume.roles[Number(found[1])]?.achievements[Number(found[2])]?.trim() || null;
}

const API = "*/api";

const ASK_LINE: Record<AskFor, string> = {
  concrete_example: "Tell me about one specific time at work. What was going on?",
  stakes: "Why did it matter? What was at stake?",
  own_role: "What did you do yourself?",
  measurable_result: "What changed in the end? A number helps, if you have one.",
  tradeoff_reasoning: "What options did you weigh, and why did you pick the one you did?",
  reflection: "Looking back, what did you learn, or what would you do differently?",
  nothing: "All five parts are there. Do you want to sharpen anything, or are you done?",
};
const PART_ASK: Record<StoryPart, AskFor> = {
  context: "concrete_example",
  stakes: "stakes",
  action: "own_role",
  result: "measurable_result",
  reflection: "reflection",
};

interface MockCoachSession {
  session: CoachSessionOut;
  turns: CoachTurnOut[];
}

/** A scripted reply: the coach's message and the parts it fills (the candidate's words). */
export interface MockCoachReply {
  message?: string;
  parts?: Partial<Record<StoryPart, string>>;
  skills?: Competency[];
  ended?: boolean;
}

let sessions = new Map<string, MockCoachSession>();
let takes: TakeOut[] = [];
let script: MockCoachReply[] = [];

export function resetMockCoach() {
  sessions = new Map();
  takes = [];
  script = [];
}

export function scriptMockCoach(replies: MockCoachReply[]) {
  script = [...replies];
}

export function mockTakes(next: TakeOut[]) {
  takes = structuredClone(next);
}

const findStory = (id: string | null) => mockStoryLibrary().find((s) => s.id === id) ?? null;
const empty = (s: Story, p: StoryPart) => !(s[p] ?? "").trim();
const missing = (s: Story | null) => STORY_PARTS.filter((p) => !s || empty(s, p));
const asking = (s: Story | null): AskFor => {
  const next = missing(s)[0];
  return next ? PART_ASK[next] : "nothing";
};

function detail(entry: MockCoachSession): CoachSessionDetail {
  const story = findStory(entry.session.story_id);
  return { session: entry.session, story, turns: entry.turns, missing: missing(story), asking_for: asking(story) };
}

function addTurn(entry: MockCoachSession, speaker: CoachTurnOut["speaker"], text: string): CoachTurnOut {
  const turn = { seq: entry.turns.length, speaker, text, at_ms: entry.turns.length * 20_000 };
  entry.turns.push(turn);
  return turn;
}

const notFound = (what: string) => HttpResponse.json({ detail: `${what} not found` }, { status: 404 });

export function coachHandlers(store?: MockStore) {
  return [
    http.post(`${API}/coach/sessions`, async ({ request }) => {
      const body = (await request.json()) as StartCoachRequest;
      let story = body.story_id ? findStory(body.story_id) : null;
      if (body.story_id && !story) return notFound("Story");
      const isNew = !story;
      const idea =
        isNew && body.resume_id && body.resume_line_ref ? ideaLine(store, body.resume_id, body.resume_line_ref) : null;
      if (isNew && body.resume_id && body.resume_line_ref && !idea) return notFound("Resume");
      if (!story) {
        const now = new Date().toISOString();
        story = mockStory({
          id: crypto.randomUUID(),
          title: idea ? idea.split(" ").slice(0, 9).join(" ") : "Untitled story",
          context: idea,
          source: "coach",
          created_at: now,
          updated_at: now,
        });
        mockStoryLibrary().push(story);
      }
      if (body.target_skill && !story.skills.includes(body.target_skill)) story.skills.push(body.target_skill);
      const id = crypto.randomUUID();
      const entry: MockCoachSession = {
        session: {
          id,
          story_id: story.id,
          style: body.style ?? "gentle",
          channel: body.channel ?? "text",
          status: "active",
          minutes: 0,
          started_at: new Date().toISOString(),
          ended_at: null,
        },
        turns: [],
      };
      const lead = idea
        ? `Let's turn this resume line into a story: "${idea}".`
        : !isNew
        ? `Let's work on "${story.title}".`
        : body.target_skill
          ? `Let's build one story that shows ${body.target_skill.replace(/_/g, " ")}, from your own work.`
          : "Let's build one story together, from your own work.";
      addTurn(entry, "coach", `${lead} ${ASK_LINE[asking(story)]}`);
      sessions.set(id, entry);
      return HttpResponse.json(detail(entry), { status: 201 });
    }),

    http.get(`${API}/coach/sessions/:id`, ({ params }) => {
      const entry = sessions.get(String(params.id));
      return entry ? HttpResponse.json(detail(entry)) : notFound("Coach session");
    }),

    http.post(`${API}/coach/sessions/:id/turns`, async ({ params, request }) => {
      const entry = sessions.get(String(params.id));
      if (!entry) return notFound("Coach session");
      if (entry.session.status !== "active") {
        return HttpResponse.json({ detail: "The coach session has ended." }, { status: 409 });
      }
      const { text } = (await request.json()) as { text: string };
      const story = findStory(entry.session.story_id);
      if (!story) return HttpResponse.json({ detail: "The story was deleted; end the session." }, { status: 409 });
      const scripted = script.shift();
      const fill = scripted?.parts ?? (missing(story)[0] ? { [missing(story)[0]]: text } : {});
      const parts = Object.entries(fill).map(([part, value]) => {
        story[part as StoryPart] = value ?? null;
        return { part: part as StoryPart, text: value ?? "", quotes: [text] };
      });
      for (const s of scripted?.skills ?? []) if (!story.skills.includes(s)) story.skills.push(s);
      story.updated_at = new Date().toISOString();
      const ask = asking(story);
      const said = addTurn(entry, "candidate", text);
      const reply = addTurn(entry, "coach", scripted?.message ?? ASK_LINE[ask]);
      if (scripted?.ended) entry.session = { ...entry.session, status: "ended", ended_at: new Date().toISOString() };
      const result: CoachTurnResult = {
        reply: { message: reply.text, parts, missing: missing(story), skills: scripted?.skills ?? story.skills },
        story,
        turns: [said, reply],
        asking_for: ask,
        conduct: "ok",
        ended: Boolean(scripted?.ended),
      };
      return HttpResponse.json(result);
    }),

    http.post(`${API}/coach/sessions/:id/style`, async ({ params, request }) => {
      const entry = sessions.get(String(params.id));
      if (!entry) return notFound("Coach session");
      const { style } = (await request.json()) as { style: CoachStyle };
      entry.session = { ...entry.session, style };
      return HttpResponse.json(entry.session);
    }),

    http.post(`${API}/coach/sessions/:id/end`, ({ params }) => {
      const entry = sessions.get(String(params.id));
      if (!entry) return notFound("Coach session");
      if (entry.session.status === "active") {
        entry.session = { ...entry.session, status: "ended", ended_at: new Date().toISOString() };
        const story = findStory(entry.session.story_id);
        if (story && story.source === "coach" && missing(story).length === STORY_PARTS.length) {
          const library = mockStoryLibrary();
          library.splice(library.indexOf(story), 1);
          entry.session = { ...entry.session, story_id: null };
        }
      }
      return HttpResponse.json(detail(entry));
    }),

    http.get(`${API}/stories/:id/takes`, ({ params }) => {
      if (!findStory(String(params.id))) return notFound("Story");
      const list = takes
        .filter((t) => t.story_id === params.id)
        .sort((a, b) => b.created_at.localeCompare(a.created_at));
      // A take is scored by the time it is read again.
      for (const t of list) {
        if (t.status !== "scoring") continue;
        const story = findStory(t.story_id);
        t.status = "scored";
        t.scores = (story?.skills ?? []).map((competency) => ({
          competency,
          score: 3,
          justification: "Clear action in your own words.",
          quotes: [t.text.slice(0, 60)],
        }));
      }
      return HttpResponse.json(list);
    }),

    http.post(`${API}/stories/:id/takes`, async ({ params, request }) => {
      const story = findStory(String(params.id));
      if (!story) return notFound("Story");
      if (story.skills.length === 0) {
        return HttpResponse.json(
          { detail: "Tag the story with at least one skill before practicing it." },
          { status: 422 },
        );
      }
      const body = (await request.json()) as TakeRequest;
      const take: TakeOut = {
        id: crypto.randomUUID(),
        story_id: story.id,
        channel: body.channel ?? "text",
        text: body.text.trim(),
        duration_s: body.duration_s ?? null,
        status: "scoring",
        scores: [],
        reason: null,
        created_at: new Date().toISOString(),
      };
      takes.push(take);
      return HttpResponse.json(take, { status: 201 });
    }),

    http.post(`${API}/stories/:id/versions`, ({ params }) => {
      const story = findStory(String(params.id));
      if (!story) return notFound("Story");
      const parts = STORY_PARTS.flatMap((p) => (empty(story, p) ? [] : [story[p] as string]));
      if (parts.length === 0) {
        return HttpResponse.json(
          { detail: "The story has no parts or takes yet, so there is nothing to write from." },
          { status: 422 },
        );
      }
      const versions: StoryVersions = {
        sixty_second: { text: parts.slice(0, 3).join(" "), quotes: parts.slice(0, 3) },
        full: { text: parts.join("\n\n"), quotes: parts },
      };
      return HttpResponse.json(versions);
    }),
  ];
}
