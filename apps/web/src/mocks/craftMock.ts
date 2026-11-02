/**
 * A small copy of strong_api.coach.craft for the mocks (SC-4, SC-5): the section order, the
 * empty required and context slots to ask about, skip and move on. Each candidate turn fills the
 * slot Strova asked about with the candidate's words, so a mock session fills section by section.
 */
import type {
  ActionStep,
  CraftAsk,
  OutlineSlot,
  SlotRef,
  StoryOutline,
  StorySection,
  StoryStyle,
} from "../pages/coach/outline";
import { EMPTY_SLOT, SECTION_SLOTS, STYLE_SECTIONS } from "../pages/coach/outline";

const CORE = new Set(["role", "problem", "did", "why", "metric", "lesson"]);
const CONTEXT = new Set(["org", "role", "scale", "timeframe", "problem", "stakeholders"]);

export const SECTION_OPENER: Record<StorySection, string> = {
  situation: "Tell me about one specific time at work: where you were, your role, and the problem you faced.",
  challenge: "Tell me about one specific challenge at work: where you were, your role, and what made it hard.",
  task: "What were you responsible for, and what would success have looked like?",
  action: "Walk me through what you did, step by step, and why.",
  result: "What changed in the end? A number helps, if you have one.",
  learning: "Looking back, what did you learn?",
};
const SLOT_QUESTION: Record<string, string> = {
  org: "Which company and team was this?",
  role: "What was your role at the time?",
  scale: "How big was it, in users, money, systems or team size?",
  timeframe: "When was this, and how long did it take?",
  problem: "What was the problem, and why was it hard?",
  stakeholders: "Who else had a stake in it, and what did each of them want?",
  did: "What did you do yourself?",
  why: "Why did you choose to do it that way?",
  metric: "What changed in the end? A number helps, if you have one.",
  lesson: "What did you learn from it?",
};
export const WRAP_LINE = "We've been through every section. Do you want to sharpen anything, or are you done?";

const EMPTY = EMPTY_SLOT;
const newStep = (): ActionStep => ({ did: null, why: null, alternatives: null, people: null });

export function emptyOutline(style: StoryStyle): StoryOutline {
  return {
    style,
    sections: STYLE_SECTIONS[style].map((section) => ({
      section,
      slots: {},
      steps: section === "action" ? [newStep()] : null,
      metric:
        section === "result"
          ? { ...EMPTY, before: null, after: null, unit: null }
          : null,
    })),
  };
}

type Section = StoryOutline["sections"][number];
const sec = (o: StoryOutline, name: StorySection) => o.sections.find((s) => s.section === name) as Section;
const slotOf = (s: Section, key: string): OutlineSlot =>
  (key === "metric" ? (s.metric as OutlineSlot | null | undefined) : s.slots?.[key]) ?? EMPTY;

export function asks(o: StoryOutline, section: StorySection): SlotRef[] {
  const s = sec(o, section);
  if (section === "action") {
    const steps = s.steps ?? [newStep()];
    if (!steps.some((st) => st.did?.status === "filled")) return [{ section, slot: "did", step: 0 }];
    if (!steps.some((st) => st.why?.status === "filled")) {
      const i = steps.findIndex((st) => st.did?.status === "filled" && st.why?.status !== "skipped");
      return i < 0 ? [] : [{ section, slot: "why", step: i }];
    }
    return [];
  }
  const keys = SECTION_SLOTS[o.style][section] ?? [];
  return keys
    .filter((k) => (CORE.has(k) || CONTEXT.has(k)) && slotOf(s, k).status === "empty")
    .map((k) => ({ section, slot: k, step: null }));
}

function hasRoom(o: StoryOutline, section: StorySection): boolean {
  if (asks(o, section).length) return true;
  if (section === "action") return false;
  const keys = SECTION_SLOTS[o.style][section] ?? [];
  return keys.some((k) => slotOf(sec(o, section), k).status === "empty");
}

export function nextSection(o: StoryOutline, after: StorySection | null): StorySection | null {
  const order = STYLE_SECTIONS[o.style];
  const start = after === null ? 0 : order.indexOf(after) + 1;
  return order.slice(start).find((s) => hasRoom(o, s)) ?? null;
}

export const askOf = (o: StoryOutline, section: StorySection | null): CraftAsk => ({
  section,
  slots: section ? asks(o, section) : [],
});

function put(o: StoryOutline, ref: SlotRef, value: OutlineSlot) {
  const s = sec(o, ref.section);
  if (ref.step !== null && ref.step !== undefined) {
    const steps = (s.steps ??= [newStep()]);
    while (steps.length <= ref.step) steps.push(newStep());
    (steps[ref.step] as Record<string, OutlineSlot | null>)[ref.slot] = value;
  } else if (ref.slot === "metric") {
    s.metric = { before: null, after: null, unit: null, ...value };
  } else {
    s.slots = { ...s.slots, [ref.slot]: value };
  }
}

const SKIP = /^(skip( it| this| that)?|pass|i can'?t share( that| it)?)[.!]?$/i;
const MOVE_ON = /^((let'?s |can we )?move on|next( section)?)[.!]?$/i;

export interface CraftStep {
  message: string;
  updates: (SlotRef & { text: string; quotes: string[] })[];
  skips: SlotRef[];
  sectionDone: boolean;
  section: StorySection | null;
}

/** One candidate turn on a styled mock story; mutates the outline. */
export function craftTurn(o: StoryOutline, section: StorySection | null, said: string): CraftStep {
  const text = said.trim();
  const short = text.split(/\s+/).join(" ");
  const asked = section ? asks(o, section) : [];
  const updates: CraftStep["updates"] = [];
  const skips: SlotRef[] = [];
  let moved = false;
  if (section && MOVE_ON.test(short)) {
    moved = true;
  } else if (section && SKIP.test(short) && asked[0]) {
    put(o, asked[0], { ...EMPTY, status: "skipped" });
    skips.push(asked[0]);
  } else if (section) {
    const keys = SECTION_SLOTS[o.style][section] ?? [];
    const target: SlotRef | undefined =
      asked[0] ?? keys.filter((k) => slotOf(sec(o, section), k).status === "empty").map((k) => ({ section, slot: k, step: null }))[0];
    if (target) {
      put(o, target, { text, quotes: [text], by_user: false, status: "filled" });
      updates.push({ ...target, text, quotes: [text] });
    }
  }
  let next = section;
  if (section && (moved || !asks(o, section).length)) next = nextSection(o, section);
  const advanced = next !== section;
  const ask = askOf(o, next);
  const message =
    next === null
      ? WRAP_LINE
      : advanced
        ? SECTION_OPENER[next]
        : ask.slots[0]
          ? SLOT_QUESTION[ask.slots[0].slot] ?? SECTION_OPENER[next]
          : SECTION_OPENER[next];
  return { message: advanced || updates.length === 0 ? message : `Thank you. ${message}`, updates, skips, sectionDone: advanced, section: next };
}

/** As strong_api.stories.outline.has_content: any slot filled. */
export function hasContent(o: StoryOutline): boolean {
  return o.sections.some(
    (s) =>
      Object.values(s.slots ?? {}).some((v) => v.status === "filled") ||
      s.metric?.status === "filled" ||
      (s.steps ?? []).some((st) => Object.values(st).some((v) => v?.status === "filled")),
  );
}

type Part = "context" | "stakes" | "action" | "result" | "reflection";
const OPENING: StorySection[] = ["situation", "challenge"];
const TASKS: StorySection[] = ["task", "challenge"];
const LEGACY: Record<Exclude<Part, "action">, [StorySection[], string][]> = {
  context: ["org", "role", "scale", "timeframe", "constraints", "stakeholders"].map((k) => [OPENING, k]),
  stakes: [[OPENING, "problem"], [TASKS, "goal"], [TASKS, "success"]],
  result: [[["result"], "metric"], [["result"], "impact"], [["result"], "evidence"]],
  reflection: [[["learning"], "lesson"], [["learning"], "differently"], [["learning"], "since"]],
};
const sentence = (t: string) => (/[.!?…:]$/.test(t.trim()) ? t.trim() : `${t.trim()}.`);

/** As strong_api.stories.outline.render_legacy (SC-14), without the Markdown details. */
export function renderLegacy(o: StoryOutline): Record<Part, string | null> {
  const text = (keys: StorySection[], key: string) => {
    const s = o.sections.find((x) => keys.includes(x.section));
    const slot = s ? slotOf(s, key) : EMPTY;
    return slot.status === "filled" && slot.text ? sentence(slot.text) : null;
  };
  const out = {} as Record<Part, string | null>;
  for (const [part, refs] of Object.entries(LEGACY) as [Exclude<Part, "action">, [StorySection[], string][]][]) {
    out[part] = refs.map(([k, key]) => text(k, key)).filter(Boolean).join(" ") || null;
  }
  const steps = sec(o, "action").steps ?? [];
  out.action =
    steps
      .map((st) => {
        const did = st.did?.status === "filled" ? st.did.text : null;
        const why = st.why?.status === "filled" ? st.why.text : null;
        if (did && why) return `${did.replace(/[ .;,]+$/, "")}, because ${why.charAt(0).toLowerCase()}${why.slice(1)}`;
        return did || why ? sentence((did ?? why) as string) : null;
      })
      .filter(Boolean)
      .map((t) => sentence(t as string))
      .join(" ") || null;
  return out;
}
