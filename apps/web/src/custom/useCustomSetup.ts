/**
 * State of the Custom setup screen (CU-1 to CU-5): categories with time shares, focus chips per
 * category, and the candidate's own questions. Focus selections are kept only once the candidate
 * changes them, so the API's preselected chips apply until then.
 */
import { useState } from "react";

import { ApiError } from "../api/client";
import { customApi } from "../api/custom";
import { useFocusSuggestions } from "../api/hooks";
import type {
  Competency,
  CustomSessionSpec,
  FocusSuggestions,
  QuestionCheckOut,
  SavedQuestion,
  StandardType,
} from "../api/types";
import {
  CHECK_MAX_EXISTING,
  categoryBlock,
  evenShares,
  fromSpecShares,
  MAX_FOCUS,
  QUESTION_CAP,
  setShare,
  setupProblems,
  toSpecCategories,
  type CategoryShare,
  type CustomDuration,
} from "./rules";

export interface OwnQuestion {
  key: string;
  text: string;
  category: StandardType;
  competencies: Competency[];
  must_ask: boolean;
  verbatim: boolean;
  saved_question_id: string | null;
  /** CU-5: the text of a near-duplicate question already in the setup. A warning only. */
  duplicateOf: string | null;
}

/** The result of a check that did not add anything, for the screen to show. */
export interface CheckNotice {
  tone: "error" | "warning";
  message: string;
}

const normalize = (text: string) => text.toLowerCase().split(/\s+/).filter(Boolean).join(" ");

/** The message for an error of the check endpoint (CU-5, CU-11). */
export function checkErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "upgrade_required") return "Custom interviews are part of the subscription.";
    return err.message;
  }
  return "We could not check this right now. Please try again.";
}

function newKey(): string {
  return globalThis.crypto.randomUUID();
}

export interface CustomSetupInit {
  duration?: CustomDuration;
  spec?: CustomSessionSpec | null;
}

export function useCustomSetup(opts: {
  jobId: string;
  resumeId: string | null;
  enabled: boolean;
  /** False for a free account: 45 minutes needs the plan (CU-11). */
  longAllowed: boolean;
  init?: CustomSetupInit;
}) {
  const init = opts.init;
  const [durationChoice, setDurationChoice] = useState<CustomDuration>(init?.duration ?? 30);
  const duration: CustomDuration = opts.longAllowed ? durationChoice : 30;
  const [shares, setShares] = useState<CategoryShare[]>(() =>
    init?.spec ? fromSpecShares(init.spec.categories) : [],
  );
  // Focus chips the candidate set, by category. Absent: the repeated setup's, else the API's preselected.
  const [focusSel, setFocusSel] = useState<Partial<Record<StandardType, string[]>>>({});
  const [extraChips, setExtraChips] = useState<Partial<Record<StandardType, string[]>>>({});
  const initialFocus: Partial<Record<StandardType, string[]>> = Object.fromEntries(
    (init?.spec?.categories ?? []).map((c) => [c.category, c.focus]),
  );
  const [questions, setQuestions] = useState<OwnQuestion[]>(() =>
    (init?.spec?.questions ?? []).map((q) => ({
      key: newKey(),
      text: q.text,
      category: q.category,
      competencies: q.competencies,
      must_ask: q.must_ask,
      verbatim: q.verbatim,
      saved_question_id: q.saved_question_id,
      duplicateOf: null,
    })),
  );

  const focus = useFocusSuggestions(opts.jobId, opts.resumeId, opts.enabled);
  const chosen = shares.map((s) => s.category);
  const cap = QUESTION_CAP[duration];

  const suggestionsFor = (c: StandardType): FocusSuggestions[StandardType] | undefined => focus.data?.[c];

  /** Every chip shown for a category: the suggestions, then the repeated setup's, then typed ones. */
  const chipsFor = (c: StandardType): string[] => {
    const all = [...(suggestionsFor(c)?.suggested ?? []), ...(initialFocus[c] ?? []), ...(extraChips[c] ?? [])];
    return [...new Set(all)];
  };
  const selectedFocus = (c: StandardType): string[] =>
    focusSel[c] ?? initialFocus[c] ?? suggestionsFor(c)?.preselected ?? [];

  const toggleCategory = (c: StandardType) => {
    if (chosen.includes(c)) {
      setShares(evenShares(chosen.filter((k) => k !== c)));
    } else if (!categoryBlock(c, chosen, duration)) {
      setShares(evenShares([...chosen, c]));
    }
  };

  const changeShare = (c: StandardType, value: number) => {
    const index = chosen.indexOf(c);
    if (index >= 0) setShares(setShare(shares, index, value));
  };

  const toggleChip = (c: StandardType, chip: string) => {
    const current = selectedFocus(c);
    const next = current.includes(chip)
      ? current.filter((x) => x !== chip)
      : current.length < MAX_FOCUS
        ? [...current, chip]
        : current;
    setFocusSel({ ...focusSel, [c]: next });
  };

  /** CU-2, CU-5: a typed chip goes through the check first. Returns a notice, or null when added. */
  const addChip = async (c: StandardType, raw: string): Promise<CheckNotice | null> => {
    const text = raw.trim();
    if (!text) return { tone: "error", message: "Type a topic first." };
    const chips = chipsFor(c);
    const same = chips.find((x) => normalize(x) === normalize(text));
    if (same) {
      if (!selectedFocus(c).includes(same)) toggleChip(c, same);
      return null;
    }
    if (selectedFocus(c).length >= MAX_FOCUS) {
      return { tone: "error", message: `Pick at most ${MAX_FOCUS} topics for one kind of question.` };
    }
    let result: QuestionCheckOut;
    try {
      result = await customApi.check({ text, kind: "focus", category: c, existing: chips.slice(0, CHECK_MAX_EXISTING) });
    } catch (err) {
      return { tone: "error", message: checkErrorMessage(err) };
    }
    if (!result.accepted) return { tone: "error", message: result.reason };
    setExtraChips((prev) => ({ ...prev, [c]: [...(prev[c] ?? []), text] }));
    setFocusSel((prev) => ({ ...prev, [c]: [...(prev[c] ?? selectedFocus(c)), text] }));
    if (result.duplicate_of !== null && chips[result.duplicate_of]) {
      return { tone: "warning", message: `Added. It is close to “${chips[result.duplicate_of]}”.` };
    }
    return null;
  };

  const exactDuplicate = (text: string) => questions.find((q) => normalize(q.text) === normalize(text));

  /** CU-3, CU-5: check and tag one typed question, then add it. Returns a notice, or null when added cleanly. */
  const addQuestion = async (raw: string): Promise<CheckNotice | null> => {
    const text = raw.trim();
    if (!text) return { tone: "error", message: "Type a question first." };
    if (questions.length >= cap) {
      return { tone: "error", message: `A ${duration}-minute session takes up to ${cap} of your questions.` };
    }
    if (exactDuplicate(text)) return { tone: "error", message: "You already added this question." };
    const existing = questions.map((q) => q.text).slice(0, CHECK_MAX_EXISTING);
    let result: QuestionCheckOut;
    try {
      result = await customApi.check({ text, kind: "question", existing });
    } catch (err) {
      return { tone: "error", message: checkErrorMessage(err) };
    }
    if (!result.accepted || !result.category) return { tone: "error", message: result.reason };
    const duplicateOf = result.duplicate_of !== null ? (existing[result.duplicate_of] ?? null) : null;
    setQuestions((prev) => [
      ...prev,
      {
        key: newKey(),
        text,
        category: result.category!,
        competencies: result.competencies,
        must_ask: true,
        verbatim: false,
        saved_question_id: null,
        duplicateOf,
      },
    ]);
    return duplicateOf ? { tone: "warning", message: "Added. It looks a lot like one of your other questions." } : null;
  };

  /** CU-8: add a saved question as it is (it was checked when it was saved). */
  const addSaved = (saved: SavedQuestion): CheckNotice | null => {
    if (questions.length >= cap) {
      return { tone: "error", message: `A ${duration}-minute session takes up to ${cap} of your questions.` };
    }
    if (exactDuplicate(saved.text)) return { tone: "error", message: "This question is already in your interview." };
    setQuestions((prev) => [
      ...prev,
      {
        key: newKey(),
        text: saved.text,
        category: saved.category,
        competencies: saved.competencies,
        must_ask: true,
        verbatim: false,
        saved_question_id: saved.id,
        duplicateOf: null,
      },
    ]);
    return null;
  };

  const updateQuestion = (key: string, patch: Partial<OwnQuestion>) =>
    setQuestions((prev) => prev.map((q) => (q.key === key ? { ...q, ...patch } : q)));

  const removeQuestion = (key: string) => setQuestions((prev) => prev.filter((q) => q.key !== key));

  /**
   * D-8: the candidate changes a question's category. The check tags it again with that category,
   * so the competencies belong to it (CU-3).
   */
  const recategorize = async (key: string, category: StandardType): Promise<CheckNotice | null> => {
    const q = questions.find((x) => x.key === key);
    if (!q || q.category === category) return null;
    let result: QuestionCheckOut;
    try {
      result = await customApi.check({ text: q.text, kind: "question", category });
    } catch (err) {
      return { tone: "error", message: checkErrorMessage(err) };
    }
    if (!result.accepted) return { tone: "error", message: result.reason };
    updateQuestion(key, { category: result.category ?? category, competencies: result.competencies });
    return null;
  };

  const stray = questions.filter((q) => !chosen.includes(q.category));
  const problems = setupProblems(shares, questions.length, duration);
  if (stray.length > 0) {
    problems.push(
      stray.length === 1
        ? "One of your questions has a kind of question that is not in this interview. Add that kind, or pick another."
        : `${stray.length} of your questions have a kind of question that is not in this interview. Add that kind, or pick another.`,
    );
  }

  const spec = (): CustomSessionSpec => ({
    categories: toSpecCategories(
      shares,
      Object.fromEntries(chosen.map((c) => [c, selectedFocus(c)])) as Partial<Record<StandardType, string[]>>,
    ),
    questions: questions.map((q) => ({
      text: q.text,
      category: q.category,
      competencies: q.competencies,
      must_ask: q.must_ask,
      verbatim: q.verbatim,
      saved_question_id: q.saved_question_id,
    })),
  });

  return {
    duration,
    setDuration: setDurationChoice,
    shares,
    chosen,
    cap,
    focus,
    chipsFor,
    selectedFocus,
    toggleCategory,
    changeShare,
    toggleChip,
    addChip,
    questions,
    addQuestion,
    addSaved,
    updateQuestion,
    removeQuestion,
    recategorize,
    problems,
    spec,
  };
}

export type CustomSetupState = ReturnType<typeof useCustomSetup>;
