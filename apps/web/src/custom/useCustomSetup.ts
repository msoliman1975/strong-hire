/**
 * State of the Custom setup screen (CU-1 to CU-5): categories with time shares, focus chips per
 * category, and the candidate's own questions. Focus selections are kept only once the candidate
 * changes them, so the API's preselected chips apply until then.
 */
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { customApi, questionRefusal } from "../api/custom";
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

/**
 * CU-5 on the server: the session start refused one own question (by key) or one focus chip.
 * The screen shows the reason next to it until the candidate changes or removes it.
 */
export type ServerRefusal =
  | { kind: "question"; key: string; reason: string }
  | { kind: "focus"; category: StandardType; chip: string; reason: string };

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
  const [questions, setQuestionsState] = useState<OwnQuestion[]>(() =>
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

  // The latest list and cap, for code that runs after an await: an add that finishes after a
  // check must see the questions added meanwhile (a saved one, another check), so the cap and
  // the duplicate rule hold (CU-3, CU-5).
  const latest = useRef(questions);
  const setQuestions = (next: (prev: OwnQuestion[]) => OwnQuestion[]) => {
    latest.current = next(latest.current);
    setQuestionsState(latest.current);
  };
  const [refusal, setRefusal] = useState<ServerRefusal | null>(null);

  const focus = useFocusSuggestions(opts.jobId, opts.resumeId, opts.enabled);
  const chosen = shares.map((s) => s.category);
  const cap = QUESTION_CAP[duration];
  const latestLimit = useRef({ cap, duration });
  useEffect(() => {
    latestLimit.current = { cap, duration };
  }, [cap, duration]);

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
    if (refusal?.kind === "focus" && refusal.category === c && refusal.chip === chip) setRefusal(null);
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
    // The updaters skip a chip that is already there, so two checks of one text add it once.
    const has = (list: string[]) => list.some((x) => normalize(x) === normalize(text));
    setExtraChips((prev) => (has(prev[c] ?? []) ? prev : { ...prev, [c]: [...(prev[c] ?? []), text] }));
    setFocusSel((prev) => {
      const current = prev[c] ?? selectedFocus(c);
      return has(current) || current.length >= MAX_FOCUS ? prev : { ...prev, [c]: [...current, text] };
    });
    if (result.duplicate_of !== null && chips[result.duplicate_of]) {
      return { tone: "warning", message: `Added. It is close to “${chips[result.duplicate_of]}”.` };
    }
    return null;
  };

  const exactDuplicate = (text: string) => latest.current.find((q) => normalize(q.text) === normalize(text));
  const atCap = () => latest.current.length >= latestLimit.current.cap;
  const capNotice = (): CheckNotice => ({
    tone: "error",
    message: `A ${latestLimit.current.duration}-minute session takes up to ${latestLimit.current.cap} of your questions.`,
  });

  /** CU-3, CU-5: check and tag one typed question, then add it. Returns a notice, or null when added cleanly. */
  const addQuestion = async (raw: string): Promise<CheckNotice | null> => {
    const text = raw.trim();
    if (!text) return { tone: "error", message: "Type a question first." };
    if (atCap()) return capNotice();
    if (exactDuplicate(text)) return { tone: "error", message: "You already added this question." };
    const existing = questions.map((q) => q.text).slice(0, CHECK_MAX_EXISTING);
    let result: QuestionCheckOut;
    try {
      result = await customApi.check({ text, kind: "question", existing });
    } catch (err) {
      return { tone: "error", message: checkErrorMessage(err) };
    }
    if (!result.accepted || !result.category) return { tone: "error", message: result.reason };
    // Again after the await: a saved question or another check may have been added meanwhile.
    if (atCap()) return capNotice();
    if (exactDuplicate(text)) return { tone: "error", message: "You already added this question." };
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
    if (atCap()) return capNotice();
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

  const clearRefusalOf = (key: string) => setRefusal((r) => (r?.kind === "question" && r.key === key ? null : r));

  const updateQuestion = (key: string, patch: Partial<OwnQuestion>) => {
    if (patch.text !== undefined || patch.category !== undefined) clearRefusalOf(key);
    setQuestions((prev) => prev.map((q) => (q.key === key ? { ...q, ...patch } : q)));
  };

  const removeQuestion = (key: string) => {
    clearRefusalOf(key);
    setQuestions((prev) => prev.filter((q) => q.key !== key));
  };

  /**
   * CU-5 on the server: `POST /sessions` answered 422 `question_refused`. Marks the refused
   * question or chip of the setup that was sent and returns true; false for any other error, or
   * when the refused text is no longer in the setup (the page then shows the error itself).
   */
  const showRefusal = (err: unknown, sent: CustomSessionSpec | null | undefined): boolean => {
    const r = questionRefusal(err);
    if (!r) return false;
    setRefusal(null);
    if (r.kind === "question" && r.index !== null) {
      const text = sent?.questions[r.index]?.text;
      const q = text !== undefined ? latest.current.find((x) => x.text === text) : latest.current[r.index];
      if (!q) return false;
      setRefusal({ kind: "question", key: q.key, reason: r.reason });
      return true;
    }
    if (r.kind === "focus" && r.index !== null) {
      const sentCategory = sent?.categories.find((x) => x.category === r.category);
      const category = (sentCategory?.category ?? r.category) as StandardType | null;
      const chip = sentCategory ? sentCategory.focus[r.index] : category ? selectedFocus(category)[r.index] : undefined;
      if (!category || chip === undefined) return false;
      setRefusal({ kind: "focus", category, chip, reason: r.reason });
      return true;
    }
    return false;
  };

  const refusalFor = (key: string): string | null =>
    refusal?.kind === "question" && refusal.key === key ? refusal.reason : null;
  const chipRefusal = (c: StandardType): { chip: string; reason: string } | null =>
    refusal?.kind === "focus" && refusal.category === c ? { chip: refusal.chip, reason: refusal.reason } : null;

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
  // CU-5: the start was refused; it stays blocked until the refused text is out of the setup.
  if (refusal?.kind === "question" && questions.some((q) => q.key === refusal.key)) {
    problems.push("One of your questions can't be used. Remove it, then start again.");
  }
  if (refusal?.kind === "focus" && chosen.includes(refusal.category) && selectedFocus(refusal.category).includes(refusal.chip)) {
    problems.push("One of your focus topics can't be used. Turn it off, then start again.");
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
    showRefusal,
    clearRefusal: () => setRefusal(null),
    refusalFor,
    chipRefusal,
    problems,
    spec,
  };
}

export type CustomSetupState = ReturnType<typeof useCustomSetup>;
