/**
 * MSW handlers for the story page's outline actions (SC-10 to SC-13), with the paths, status codes
 * and bodies of strong_api.stories.outline_api. Improve tightens the section's first filled slot
 * Strova wrote (or asks a question), Organize sorts a classic story's five parts into STAR slots,
 * and Switch moves the Task slots in or out of Challenge. Every write renders the five parts.
 */
import { http, HttpResponse } from "msw/http";

import type { OutlineSlot, StoryOutline, StorySection, StoryStyle } from "../pages/coach/outline";
import { EMPTY_SLOT } from "../pages/coach/outline";
import type { OutlinePatch, SlotEdit, Story } from "../pages/stories/api";
import { emptyOutline, renderLegacy } from "./craftMock";

const API = "*/api";
const TASK = ["goal", "success", "assigned_by"];

type Section = StoryOutline["sections"][number];
type Metric = NonNullable<Section["metric"]>;

const sec = (o: StoryOutline, name: StorySection) => o.sections.find((s) => s.section === name);
const filled = (text: string, byUser: boolean, quotes: string[] = []): OutlineSlot => ({
  text,
  quotes: byUser ? [] : quotes,
  by_user: byUser,
  status: "filled",
});

function putSlot(s: Section, key: string, step: number | null | undefined, value: OutlineSlot, numbers: Partial<Metric> = {}) {
  if (step !== null && step !== undefined) {
    const steps = (s.steps ??= []);
    while (steps.length <= step) steps.push({ did: null, why: null, alternatives: null, people: null });
    (steps[step] as Record<string, OutlineSlot | null>)[key] = value;
  } else if (key === "metric") {
    s.metric = { before: null, after: null, unit: null, ...value, ...numbers };
  } else {
    s.slots = { ...s.slots, [key]: value };
  }
}

function sectionFor(o: StoryOutline, wanted: StorySection): Section | undefined {
  return sec(o, wanted) ?? (["situation", "challenge", "task"].includes(wanted) ? o.sections[0] : undefined);
}

export function convertStyle(o: StoryOutline, style: StoryStyle): StoryOutline {
  if (o.style === style) return structuredClone(o);
  const out = emptyOutline(style);
  for (const s of o.sections) {
    for (const [key, value] of Object.entries(s.slots)) {
      const target = style === "carl" ? out.sections[0] : TASK.includes(key) ? sec(out, "task")! : sec(out, "situation")!;
      target.slots[key] = value;
    }
    if (s.section === "action") sec(out, "action")!.steps = structuredClone(s.steps);
    if (s.section === "result") sec(out, "result")!.metric = structuredClone(s.metric);
  }
  return out;
}

function save(story: Story, outline: StoryOutline) {
  story.style = outline.style;
  story.outline = outline;
  Object.assign(story, renderLegacy(outline));
  story.updated_at = new Date().toISOString();
}

const conflict = (code: string, message: string) => HttpResponse.json({ detail: { code, message } }, { status: 409 });
const invalid = (msg: string) => HttpResponse.json({ detail: msg }, { status: 422 });

export function outlineHandlers(find: (id: string) => Story | undefined, out: (s: Story) => Story) {
  return [
    http.patch(`${API}/stories/:id/outline`, async ({ params, request }) => {
      const story = find(String(params.id));
      if (!story) return HttpResponse.json({ detail: "Story not found" }, { status: 404 });
      if (!story.outline) return conflict("classic_story", "Organize this story into sections first.");
      const body = (await request.json()) as OutlinePatch;
      const outline = structuredClone(story.outline);
      for (const e of body.slots ?? []) {
        const s = sectionFor(outline, e.section);
        if (!s) return invalid("Not a slot of this story");
        if (e.step !== null && e.step !== undefined && e.step > (s.steps?.length ?? 0)) return invalid("Steps are added in order");
        if (e.step !== null && e.step !== undefined && e.step >= 5) return invalid("At most 5 steps");
        const text = (e.text ?? "").trim();
        const value = e.skipped ? { ...EMPTY_SLOT, status: "skipped" as const } : text ? filled(text, true) : EMPTY_SLOT;
        putSlot(s, e.slot, e.step, value, e.slot === "metric" ? { before: e.before ?? null, after: e.after ?? null, unit: e.unit ?? null } : {});
      }
      if (body.steps) {
        const action = sec(outline, "action")!;
        const steps = action.steps ?? [];
        if (new Set(body.steps).size !== body.steps.length || body.steps.some((i) => i < 0 || i >= steps.length)) {
          return invalid("steps must list existing step numbers, each once");
        }
        action.steps = body.steps.map((i) => steps[i]);
      }
      save(story, outline);
      return HttpResponse.json(out(story));
    }),

    http.post(`${API}/stories/:id/sections/:section/improve`, ({ params }) => {
      const story = find(String(params.id));
      if (!story?.outline) return conflict("classic_story", "Organize this story into sections first.");
      const s = sectionFor(story.outline, params.section as StorySection);
      if (!s) return HttpResponse.json({ detail: "This story has no such section" }, { status: 404 });
      const candidates: { slot: string; step: number | null; value: OutlineSlot }[] = [
        ...Object.entries(s.slots).map(([slot, value]) => ({ slot, step: null, value })),
        ...(s.metric ? [{ slot: "metric", step: null, value: s.metric as OutlineSlot }] : []),
        ...(s.steps ?? []).flatMap((st, i) =>
          Object.entries(st).map(([slot, value]) => ({ slot, step: i, value: value ?? EMPTY_SLOT })),
        ),
      ];
      const first = candidates.find((c) => c.value.status === "filled" && c.value.text);
      if (!first) return HttpResponse.json({ edits: [], questions: ["What did you do yourself, step by step?"] });
      const before = first.value.text as string;
      // A shorter telling in the user's own words: the first clause, or "I" for "we".
      const head = before.split(/,\s+(?:and|but|so)\s+/)[0].replace(/[.\s]+$/, "");
      const after = (head.length < before.length - 2 ? `${head}.` : before.replace(/^(we|our team)\b/i, "I")).trim();
      const edit: SlotEdit = {
        section: s.section,
        slot: first.slot,
        step: first.step,
        before,
        after: after === before ? `${before.replace(/[.\s]+$/, "")}.` : after,
        quotes: [before],
      };
      return HttpResponse.json({ edits: [edit], questions: [] });
    }),

    http.post(`${API}/stories/:id/sections/:section/improve/accept`, async ({ params, request }) => {
      const story = find(String(params.id));
      if (!story?.outline) return conflict("classic_story", "Organize this story into sections first.");
      const { edits } = (await request.json()) as { edits: SlotEdit[] };
      const outline = structuredClone(story.outline);
      for (const e of edits) {
        const s = sectionFor(outline, e.section);
        if (!s) return invalid("Not a slot of this section");
        putSlot(s, e.slot, e.step, filled(e.after, false, e.quotes));
      }
      save(story, outline);
      return HttpResponse.json(out(story));
    }),

    http.post(`${API}/stories/:id/organize`, ({ params }) => {
      const story = find(String(params.id));
      if (!story) return HttpResponse.json({ detail: "Story not found" }, { status: 404 });
      if (story.outline) return conflict("styled_story", "This story is already organized in sections.");
      const outline = emptyOutline("star");
      const q = (t: string) => [t];
      if (story.context) putSlot(outline.sections[0], "role", null, filled(story.context, false, q(story.context)));
      if (story.stakes) putSlot(outline.sections[0], "problem", null, filled(story.stakes, false, q(story.stakes)));
      if (story.action) putSlot(sec(outline, "action")!, "did", 0, filled(story.action, false, q(story.action)));
      if (story.result) putSlot(sec(outline, "result")!, "metric", null, filled(story.result, false, q(story.result)));
      if (story.reflection) putSlot(sec(outline, "learning")!, "lesson", null, filled(story.reflection, false, q(story.reflection)));
      return HttpResponse.json({ outline });
    }),

    http.post(`${API}/stories/:id/organize/accept`, async ({ params, request }) => {
      const story = find(String(params.id));
      if (!story) return HttpResponse.json({ detail: "Story not found" }, { status: 404 });
      if (story.outline) return conflict("styled_story", "This story is already organized in sections.");
      const { outline } = (await request.json()) as { outline: StoryOutline };
      save(story, outline);
      return HttpResponse.json(out(story));
    }),

    http.post(`${API}/stories/:id/style`, async ({ params, request }) => {
      const story = find(String(params.id));
      if (!story?.outline) return conflict("classic_story", "Organize this story into sections first.");
      const { style, rewrite } = (await request.json()) as { style: StoryStyle; rewrite?: boolean };
      const moved = convertStyle(story.outline, style);
      if (rewrite) return HttpResponse.json({ story: null, preview: moved });
      if (story.outline.style !== style) save(story, moved);
      return HttpResponse.json({ story: out(story), preview: null });
    }),

    http.post(`${API}/stories/:id/style/accept`, async ({ params, request }) => {
      const story = find(String(params.id));
      if (!story?.outline) return conflict("classic_story", "Organize this story into sections first.");
      const outline = (await request.json()) as StoryOutline;
      if (outline.style === story.outline.style) return conflict("styled_story", "The story is already in this style.");
      save(story, outline);
      return HttpResponse.json(out(story));
    }),
  ];
}

/** A mock styled story for tests and the seed: STAR, partly filled from the candidate's words. */
export function mockOutline(style: StoryStyle = "star"): StoryOutline {
  const o = emptyOutline(style);
  const open = o.sections[0];
  putSlot(open, "role", null, filled("I was the tech lead on checkout.", false, ["I was the tech lead on checkout"]));
  putSlot(open, "problem", null, filled("The payments migration was two weeks late.", true));
  putSlot(open, "org", null, { ...EMPTY_SLOT, status: "skipped" });
  putSlot(sec(o, "action")!, "did", 0, filled("I split the rollout by country.", true));
  putSlot(sec(o, "result")!, "metric", null, filled("Checkout errors fell from 2% to 0.3%.", true), {
    before: "2",
    after: "0.3",
    unit: "%",
  });
  return o;
}

// --- SC-8, SC-9: flow flags and skill hints ---------------------------------------------------

type FlowFlag = Story["flow_flags"][number];
type FlagType = FlowFlag["type"];
type Ref = FlowFlag["slots"][number];

const QUESTIONS: Record<FlagType, string> = {
  action_vs_problem: "How did what you did address the problem you named?",
  result_vs_problem: "Did the result solve the problem you started with, and how do you know?",
  number_conflict: "Two of your numbers seem to disagree. Which one is right?",
  timeline_conflict: "The timing doesn't line up. What happened in between?",
  loose_end: "You named someone with a stake in this. What happened with them?",
};

/** As the API's fake fixture: one flag of each type, citing slots that have text. */
export function mockFlags(o: StoryOutline): FlowFlag[] {
  const refs: Ref[] = [];
  for (const s of o.sections) {
    for (const [slot, v] of Object.entries(s.slots)) if (v.status === "filled") refs.push({ section: s.section, slot, step: null });
    if (s.metric?.status === "filled") refs.push({ section: s.section, slot: "metric", step: null });
    (s.steps ?? []).forEach((st, i) => {
      if (st.did?.status === "filled") refs.push({ section: s.section, slot: "did", step: i });
    });
  }
  if (!refs.length) return [];
  const pair = refs.length > 1 ? [refs[0], refs[refs.length - 1]] : [refs[0]];
  return (Object.keys(QUESTIONS) as FlagType[]).map((type, i) => {
    const slots = i % 2 ? [pair[0]] : pair;
    return { key: `${type}:${slots.map((r) => `${r.section}.${r.slot}`).join(":")}`, type, slots, question: QUESTIONS[type] };
  });
}

export const MOCK_HINTS = [
  { skill: "collaboration", reason: "You brought three teams along to the plan." },
  { skill: "judgment", reason: "You chose a small first step over one big switch." },
] as Story["hints"];

export function flowHandlers(find: (id: string) => Story | undefined, out: (s: Story) => Story) {
  const styled = (id: string) => {
    const story = find(id);
    return story?.outline ? story : null;
  };
  const classic = () => conflict("classic_story", "Organize this story into sections first.");
  return [
    http.post(`${API}/stories/:id/flow-check`, ({ params }) => {
      const story = styled(String(params.id));
      if (!story?.outline) return classic();
      story.flow_flags = mockFlags(story.outline);
      return HttpResponse.json(out(story));
    }),
    http.post(`${API}/stories/:id/flow-flags/:key/dismiss`, ({ params }) => {
      const story = styled(String(params.id));
      if (!story) return classic();
      story.flow_flags = story.flow_flags.filter((f) => f.key !== params.key);
      return HttpResponse.json(out(story));
    }),
    http.post(`${API}/stories/:id/hints/:skill/:action`, ({ params }) => {
      const story = styled(String(params.id));
      if (!story) return classic();
      const skill = String(params.skill) as Story["hints"][number]["skill"];
      if (!story.hints.some((h) => h.skill === skill)) return HttpResponse.json({ detail: "No such hint" }, { status: 404 });
      story.hints = story.hints.filter((h) => h.skill !== skill);
      if (params.action === "deepen" && !story.skills.includes(skill)) story.skills.push(skill);
      return HttpResponse.json(out(story));
    }),
  ];
}

/** SC-1, SC-10: a story written in STAR or CARL: the user's typed slots in an empty outline. */
export function writtenOutline(style: StoryStyle, slots: OutlinePatch["slots"] = []): StoryOutline {
  const outline = emptyOutline(style);
  for (const e of slots ?? []) {
    const s = sectionFor(outline, e.section);
    const text = (e.text ?? "").trim();
    if (!s || !text) continue;
    putSlot(s, e.slot, e.step, filled(text, true), e.slot === "metric" ? { before: e.before ?? null, after: e.after ?? null, unit: e.unit ?? null } : {});
  }
  return outline;
}
