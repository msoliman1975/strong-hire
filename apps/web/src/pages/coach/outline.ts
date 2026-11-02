/**
 * The outline of a styled story (SC-2) on the client: sections and slots from the spec's table
 * (docs/story-crafting-spec.md, "Sections and slots"), the labels, and Ready (SC-3, D-4). The API
 * is the source of truth; these mirror strong_core.schemas.stories for display.
 */
import type { components } from "../../api/schema.gen";
import type { Story } from "../stories/api";

type S = components["schemas"];

export type StoryStyle = S["StoryStyle"];
export type StorySection = S["StorySection"];
export type SlotStatus = S["SlotStatus"];
/** As the API sends it: every field present (Story is DeepRequired). */
export type StoryOutline = NonNullable<Story["outline"]>;
export type OutlineSlot = StoryOutline["sections"][number]["slots"][string];
export type ActionStep = NonNullable<StoryOutline["sections"][number]["steps"]>[number];
export type SlotRef = S["SlotRef"];
export type CraftAsk = S["CraftAsk"];

export const STYLE_SECTIONS: Record<StoryStyle, StorySection[]> = {
  star: ["situation", "task", "action", "result", "learning"],
  carl: ["challenge", "action", "result", "learning"],
};

export const STYLE_NAME: Record<StoryStyle, string> = { star: "STAR", carl: "CARL" };

/** D-1: one line on what each style's sections are. */
export const STYLE_DESCRIPTION: Record<StoryStyle, string> = {
  star: "Situation, Task, Action, Result, Learning. A clear arc for most stories.",
  carl: "Challenge, Action, Result, Learning. Leads with the hard part: conflict, failure, a tough call.",
};

export const SECTION_LABEL: Record<StorySection, string> = {
  situation: "Situation",
  challenge: "Challenge",
  task: "Task",
  action: "Action",
  result: "Result",
  learning: "Learning",
};

const CONTEXT = ["org", "role", "scale", "timeframe", "problem", "constraints", "stakeholders"];
const TASK = ["goal", "success", "assigned_by"];
const RESULT = ["metric", "impact", "evidence", "recognition"];
const LEARNING = ["lesson", "differently", "since"];
export const STEP_FIELDS = ["did", "why", "alternatives", "people"] as const;

/** The named slots of each section, in display order (Action holds steps instead). */
export const SECTION_SLOTS: Record<StoryStyle, Partial<Record<StorySection, string[]>>> = {
  star: { situation: CONTEXT, task: TASK, action: [], result: RESULT, learning: LEARNING },
  carl: { challenge: [...CONTEXT, ...TASK], action: [], result: RESULT, learning: LEARNING },
};

export const SLOT_LABEL: Record<string, string> = {
  org: "Company and team",
  role: "Your role at the time",
  scale: "Scale",
  timeframe: "When, and how long",
  problem: "The problem, and why it was hard",
  constraints: "Constraints",
  stakeholders: "Stakeholders, and what each wanted",
  goal: "Your goal or responsibility",
  success: "What success looked like",
  assigned_by: "Who gave it to you",
  did: "What you did",
  why: "Why you did it",
  alternatives: "What else you weighed",
  people: "How you brought people along",
  metric: "A metric, before and after",
  impact: "Business or customer impact",
  evidence: "How you knew it worked",
  recognition: "Recognition",
  lesson: "The lesson",
  differently: "What you'd do differently",
  since: "Where you've used it since",
};

/** D-4: the slots Ready needs. `did` and `why` count once at least one step has each. */
export const CORE_SLOTS = new Set(["role", "problem", "did", "why", "metric", "lesson"]);
/** D-5: the context slots Strova asks for once each. */
export const CONTEXT_SLOTS = new Set(["org", "role", "scale", "timeframe", "problem", "stakeholders"]);

export const EMPTY_SLOT: OutlineSlot = { status: "empty", quotes: [], by_user: false, text: null };

export interface SlotView {
  section: StorySection;
  key: string;
  step: number | null;
  slot: OutlineSlot;
}

const EMPTY = EMPTY_SLOT;

type Section = StoryOutline["sections"][number];

function named(section: Section, key: string): OutlineSlot {
  if (key === "metric") return (section.metric as OutlineSlot | null | undefined) ?? EMPTY;
  return section.slots?.[key] ?? EMPTY;
}

/** The slots of one section in display order; unwritten ones come back empty. */
export function sectionSlots(outline: StoryOutline, section: Section): SlotView[] {
  if (section.section === "action") {
    return (section.steps ?? []).flatMap((step, i) =>
      STEP_FIELDS.map((key) => ({ section: section.section, key, step: i, slot: step[key] ?? EMPTY })),
    );
  }
  const keys = SECTION_SLOTS[outline.style][section.section] ?? [];
  return keys.map((key) => ({ section: section.section, key, step: null, slot: named(section, key) }));
}

export const isFilled = (slot: OutlineSlot | null | undefined) => slot?.status === "filled" && !!slot.text;

/** SC-3, D-4: Ready when every core slot is filled. */
export function outlineReady(outline: StoryOutline): boolean {
  const opening = outline.sections[0];
  const find = (name: StorySection) => outline.sections.find((s) => s.section === name);
  const steps = find("action")?.steps ?? [];
  const result = find("result");
  const learning = find("learning");
  return (
    !!opening &&
    isFilled(named(opening, "role")) &&
    isFilled(named(opening, "problem")) &&
    steps.some((s) => isFilled(s.did)) &&
    steps.some((s) => isFilled(s.why)) &&
    !!result &&
    isFilled(named(result, "metric")) &&
    !!learning &&
    isFilled(named(learning, "lesson"))
  );
}

const idOf = (section: StorySection, key: string, step: number | null | undefined) =>
  `${section}.${key}${step === null || step === undefined ? "" : `[${step}]`}`;

/** A stable id for a slot ref (from the API) or a slot view (in the panel). */
export const refId = (r: SlotRef) => idOf(r.section, r.slot, r.step);
export const viewId = (v: SlotView) => idOf(v.section, v.key, v.step);

export const STATUS_TEXT: Record<SlotStatus, string> = { filled: "Filled", empty: "Empty", skipped: "Skipped" };
