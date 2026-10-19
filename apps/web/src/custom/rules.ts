/**
 * The Custom setup rules the screen enforces before the API sees the setup (CU-1, CU-3, D-3,
 * D-5). They mirror `strong_core.schemas.custom` so the candidate gets an explanation instead of
 * a 422; the API stays the authority and refuses anything that slips through.
 *
 * Shares are whole percents in 5% steps here and fractions (0 to 1) on the wire.
 */
import type { CustomSessionSpec, StandardType } from "../api/types";

export type CustomDuration = 30 | 45;

export const CATEGORIES: StandardType[] = ["behavioral", "technical_qa", "hiring_manager", "case"];
export const MAX_CATEGORIES = 3;
export const SHARE_STEP = 5;
export const MIN_SHARE = 15;
export const CASE_MIN_SHARE = 50;
export const CASE_MIN_DURATION: CustomDuration = 45;
/** D-3: Case and at most one other category. */
export const CASE_MAX_CATEGORIES = 2;

/** D-5, CU-3: own questions per session length. */
export const QUESTION_CAP: Record<CustomDuration, number> = { 30: 5, 45: 8 };
/** About how many questions a session has (QUESTIONS_BY_DURATION in the worker's brief). */
export const QUESTIONS_BY_DURATION: Record<CustomDuration, number> = { 30: 8, 45: 10 };
/** Minutes of core questions in the default time plan (strong_interview.controller). */
export const CORE_MINUTES: Record<CustomDuration, number> = { 30: 21, 45: 35 };

export const QUESTION_MAX_LEN = 500;
export const FOCUS_MAX_LEN = 60;
export const MAX_FOCUS = 8;
/** The check's `existing` list holds at most this many entries. */
export const CHECK_MAX_EXISTING = 20;

export interface CategoryShare {
  category: StandardType;
  /** Whole percent, a multiple of SHARE_STEP. */
  share: number;
}

/** The smallest share a category may have in a setup of `count` categories. */
export function minShare(category: StandardType, count: number): number {
  if (count <= 1) return 100;
  return category === "case" ? CASE_MIN_SHARE : MIN_SHARE;
}

/**
 * The default even split in 5% steps; Case gets its minimum when the even share is lower. The
 * rounding remainder goes to the first categories so the total is 100.
 */
export function evenShares(categories: StandardType[]): CategoryShare[] {
  const n = categories.length;
  if (n === 0) return [];
  const caseFirst = categories.includes("case") && n > 1;
  const base = Math.floor(100 / n / SHARE_STEP) * SHARE_STEP;
  const shares = categories.map((category) => ({ category, share: base }));
  if (caseFirst) {
    const c = shares.find((s) => s.category === "case")!;
    c.share = Math.max(c.share, CASE_MIN_SHARE);
    const others = shares.filter((s) => s.category !== "case");
    const rest = 100 - c.share;
    const each = Math.floor(rest / others.length / SHARE_STEP) * SHARE_STEP;
    for (const o of others) o.share = each;
  }
  let left = 100 - shares.reduce((sum, s) => sum + s.share, 0);
  for (let i = 0; left > 0; i = (i + 1) % n) {
    shares[i].share += SHARE_STEP;
    left -= SHARE_STEP;
  }
  return shares;
}

/** The largest share `index` can take while every other category keeps its minimum. */
export function maxShare(shares: CategoryShare[], index: number): number {
  const others = shares.filter((_, i) => i !== index);
  return 100 - others.reduce((sum, s) => sum + minShare(s.category, shares.length), 0);
}

/**
 * Sets one category's share and takes the difference from (or gives it to) the others, last
 * first, so the shares always add up to 100 and no category drops below its minimum.
 */
export function setShare(shares: CategoryShare[], index: number, value: number): CategoryShare[] {
  const n = shares.length;
  if (n <= 1) return shares.map((s) => ({ ...s, share: 100 }));
  const lo = minShare(shares[index].category, n);
  const hi = maxShare(shares, index);
  const wanted = Math.min(hi, Math.max(lo, Math.round(value / SHARE_STEP) * SHARE_STEP));
  const next = shares.map((s) => ({ ...s }));
  let delta = wanted - next[index].share;
  next[index].share = wanted;
  const order = next.map((_, i) => i).filter((i) => i !== index).reverse();
  if (delta > 0) {
    for (const j of order) {
      const room = next[j].share - minShare(next[j].category, n);
      const take = Math.min(room, delta);
      next[j].share -= take;
      delta -= take;
      if (delta === 0) break;
    }
  } else if (delta < 0) {
    next[order[0]].share -= delta;
  }
  return next;
}

/** Why a category cannot be added now, or null when it can (CU-1, D-3). */
export function categoryBlock(
  category: StandardType,
  chosen: StandardType[],
  duration: CustomDuration,
): string | null {
  if (chosen.includes(category)) return null;
  if (chosen.length >= MAX_CATEGORIES) return `Pick at most ${MAX_CATEGORIES} kinds of question.`;
  if (category === "case") {
    if (duration < CASE_MIN_DURATION) return "A case needs about 20 minutes, so it needs a 45-minute session.";
    if (chosen.length >= CASE_MAX_CATEGORIES) return "A case allows at most one other kind of question.";
  }
  if (chosen.includes("case") && chosen.length >= CASE_MAX_CATEGORIES) {
    return "With a case, you can add one other kind of question.";
  }
  return null;
}

/** Problems that block the start, in words. Empty when the setup can start. */
export function setupProblems(
  shares: CategoryShare[],
  questionCount: number,
  duration: CustomDuration,
): string[] {
  const out: string[] = [];
  if (shares.length === 0) out.push("Pick at least one kind of question.");
  const total = shares.reduce((sum, s) => sum + s.share, 0);
  if (shares.length > 0 && total !== 100) out.push(`The time shares add up to ${total}%, not 100%.`);
  if (shares.some((s) => s.category === "case") && duration < CASE_MIN_DURATION) {
    out.push("A case needs a 45-minute session.");
  }
  if (questionCount > QUESTION_CAP[duration]) {
    out.push(`A ${duration}-minute session takes up to ${QUESTION_CAP[duration]} of your questions. Remove some.`);
  }
  return out;
}

/** "About 8 questions: 3 of yours, 5 chosen by the interviewer from your focus areas." */
export function planSummary(duration: CustomDuration, own: number): string {
  const total = QUESTIONS_BY_DURATION[duration];
  const yours = Math.min(own, total);
  const theirs = Math.max(0, total - yours);
  return `About ${total} questions: ${yours} of yours, ${theirs} chosen by the interviewer from your focus areas.`;
}

/** Approximate minutes of core questions for a share. */
export function shareMinutes(duration: CustomDuration, share: number): number {
  return Math.round((CORE_MINUTES[duration] * share) / 100);
}

/** The wire shape of the setup's categories. */
export function toSpecCategories(
  shares: CategoryShare[],
  focus: Partial<Record<StandardType, string[]>>,
): CustomSessionSpec["categories"] {
  return shares.map((s) => ({ category: s.category, share: s.share / 100, focus: (focus[s.category] ?? []).slice(0, MAX_FOCUS) }));
}

/** Percent shares from the wire (a repeated setup), snapped to 5% steps and fixed to add up to 100. */
export function fromSpecShares(categories: CustomSessionSpec["categories"]): CategoryShare[] {
  const shares = categories.map((c) => ({
    category: c.category,
    share: Math.round((c.share * 100) / SHARE_STEP) * SHARE_STEP,
  }));
  const total = shares.reduce((sum, s) => sum + s.share, 0);
  if (shares.length > 0 && total !== 100) shares[0].share += 100 - total;
  return shares;
}
