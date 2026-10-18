/**
 * The Custom part of the session setup (journey steps 2 to 4, CU-1 to CU-5, CU-8): length,
 * kinds of question with their time shares, focus chips, and the candidate's own questions.
 * Difficulty, mode and level stay on the setup page, as for the other types.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import { savedQuestionsApi } from "../api/custom";
import { keys, useSavedQuestions } from "../api/hooks";
import type { StandardType } from "../api/types";
import { Choices } from "../components/Choices";
import { competencyLabel, interviewTypeHint, interviewTypeLabel } from "../labels";
import {
  CATEGORIES,
  categoryBlock,
  FOCUS_MAX_LEN,
  MAX_FOCUS,
  maxShare,
  minShare,
  planSummary,
  QUESTION_CAP,
  QUESTION_MAX_LEN,
  SHARE_STEP,
  shareMinutes,
  type CustomDuration,
} from "./rules";
import type { CheckNotice, CustomSetupState, OwnQuestion } from "./useCustomSetup";

const DURATIONS: `${CustomDuration}`[] = ["30", "45"];

function Notice({ notice, id }: { notice: CheckNotice | null; id?: string }) {
  if (!notice) return null;
  return (
    <p
      id={id}
      className={notice.tone === "error" ? "field-error" : "hint"}
      role={notice.tone === "error" ? "alert" : "status"}
    >
      {notice.message}
    </p>
  );
}

export function CustomFields({ setup, longAllowed }: { setup: CustomSetupState; longAllowed: boolean }) {
  return (
    <div className="custom-setup">
      <Choices
        legend="Duration"
        name="custom-duration"
        options={DURATIONS}
        value={String(setup.duration) as `${CustomDuration}`}
        onChange={(v) => setup.setDuration(Number(v) as CustomDuration)}
        label={(v) => `${v} minutes`}
        hint={(v) =>
          v === "30"
            ? `Up to ${QUESTION_CAP[30]} of your own questions.`
            : longAllowed
              ? `Up to ${QUESTION_CAP[45]} of your own questions. Needed for a case.`
              : "Needs a subscription."
        }
        disabled={(v) => v === "45" && !longAllowed}
        describedBy={longAllowed ? undefined : "custom-duration-hint"}
      />
      {!longAllowed && (
        <p className="hint" id="custom-duration-hint">
          A free account can run a 30-minute Custom interview as one of its free interviews. 45 minutes needs the plan.{" "}
          <Link to="/upgrade">See the monthly plan</Link>
        </p>
      )}

      <CategoryPicker setup={setup} />

      {setup.shares.map((s) => (
        <CategorySection key={s.category} setup={setup} category={s.category} />
      ))}

      <OwnQuestions setup={setup} />

      <div className="custom-summary" data-testid="custom-summary">
        <p>
          <strong>{planSummary(setup.duration, setup.questions.length)}</strong>
        </p>
        {setup.problems.length > 0 && (
          <ul className="field-error" data-testid="custom-problems">
            {setup.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** CU-1: 1 to 3 kinds of question. Case needs 45 minutes and at most one other kind (D-3). */
function CategoryPicker({ setup }: { setup: CustomSetupState }) {
  return (
    <fieldset>
      <legend className="label">Kinds of question (pick 1 to 3)</legend>
      <div className="choices">
        {CATEGORIES.map((c) => {
          const on = setup.chosen.includes(c);
          const block = on ? null : categoryBlock(c, setup.chosen, setup.duration);
          return (
            <label key={c} className="choice">
              <input
                type="checkbox"
                name="custom-category"
                value={c}
                checked={on}
                disabled={block !== null}
                onChange={() => setup.toggleCategory(c)}
              />
              <span className="choice__name">{interviewTypeLabel[c]}</span>
              <span className="choice__hint">{block ?? interviewTypeHint[c]}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Time share (CU-1) and focus chips (CU-2) of one kind of question. */
function CategorySection({ setup, category }: { setup: CustomSetupState; category: StandardType }) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<CheckNotice | null>(null);
  const [checking, setChecking] = useState(false);
  const index = setup.chosen.indexOf(category);
  const share = setup.shares[index]?.share ?? 0;
  const count = setup.shares.length;
  const name = interviewTypeLabel[category];
  const chips = setup.chipsFor(category);
  const selected = setup.selectedFocus(category);
  const full = selected.length >= MAX_FOCUS;

  const add = async () => {
    setChecking(true);
    setNotice(null);
    const result = await setup.addChip(category, draft);
    setChecking(false);
    setNotice(result);
    if (!result || result.tone === "warning") setDraft("");
  };

  return (
    <section className="custom-category" aria-labelledby={`${id}-title`}>
      <div className="row row--between">
        <h3 id={`${id}-title`}>{name}</h3>
        <span className="muted" data-testid={`share-${category}`}>
          {share}%, about {shareMinutes(setup.duration, share)} min
        </span>
      </div>
      {count > 1 && (
        <div className="field">
          <label htmlFor={`${id}-share`}>Time for {name}</label>
          <input
            id={`${id}-share`}
            type="range"
            min={0}
            max={100}
            step={SHARE_STEP}
            value={share}
            aria-valuetext={`${share}%`}
            aria-describedby={`${id}-share-hint`}
            onChange={(e) => setup.changeShare(category, Number(e.target.value))}
          />
          <p className="hint" id={`${id}-share-hint`}>
            Between {minShare(category, count)}% and {maxShare(setup.shares, index)}%.
            {category === "case" ? " A case needs at least half the time." : ""}
          </p>
        </div>
      )}
      <fieldset>
        <legend className="label">Focus topics</legend>
        {setup.focus.isPending && <p className="muted small">Loading suggested topics</p>}
        {chips.length === 0 && !setup.focus.isPending && (
          <p className="muted small">No suggested topics. Add your own, or let the interviewer choose.</p>
        )}
        <div className="chip-list">
          {chips.map((chip) => {
            const on = selected.includes(chip);
            return (
              <button
                key={chip}
                type="button"
                className="chip chip--toggle"
                aria-pressed={on}
                disabled={!on && full}
                onClick={() => setup.toggleChip(category, chip)}
              >
                {chip}
              </button>
            );
          })}
        </div>
        <div className="field__row section">
          <label className="visually-hidden" htmlFor={`${id}-chip`}>
            Add a focus topic for {name}
          </label>
          <input
            id={`${id}-chip`}
            type="text"
            maxLength={FOCUS_MAX_LEN}
            placeholder="Add a topic, for example conflict"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void add();
              }
            }}
          />
          <button type="button" className="btn btn--secondary" disabled={checking || !draft.trim()} onClick={() => void add()}>
            {checking ? "Checking" : "Add topic"}
          </button>
        </div>
        <Notice notice={notice} />
      </fieldset>
    </section>
  );
}

/** CU-3, CU-4, CU-5, CU-8: the candidate's own questions. */
function OwnQuestions({ setup }: { setup: CustomSetupState }) {
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<CheckNotice | null>(null);
  const [checking, setChecking] = useState(false);
  const saved = useSavedQuestions();
  const count = setup.questions.length;
  const atCap = count >= setup.cap;
  const nearCap = !atCap && count >= setup.cap - 1 && count > 0;

  const add = async () => {
    setChecking(true);
    setNotice(null);
    const result = await setup.addQuestion(draft);
    setChecking(false);
    setNotice(result);
    if (!result || result.tone === "warning") setDraft("");
  };

  const inSetup = new Set(setup.questions.map((q) => q.saved_question_id).filter(Boolean));
  const savedLeft = (saved.data ?? []).filter((q) => !inSetup.has(q.id));

  return (
    <section className="custom-questions" aria-labelledby="own-questions-heading">
      <h3 id="own-questions-heading">Your questions</h3>
      <p className="muted">
        Optional. Add questions you expect, for example one a recruiter warned you about. Up to {setup.cap} in a{" "}
        {setup.duration}-minute session.
      </p>
      {setup.questions.length > 0 && (
        <ol className="plain-list own-question-list">
          {setup.questions.map((q) => (
            <OwnQuestionItem key={q.key} setup={setup} q={q} />
          ))}
        </ol>
      )}
      {nearCap && (
        <p className="notice" role="status" data-testid="cap-warning">
          Not all of your questions may fit. The interviewer asks the must-ask ones first and cuts follow-ups to make
          room.
        </p>
      )}
      {atCap ? (
        <p className="hint" data-testid="cap-reached">
          You added {setup.cap} questions, the most for a {setup.duration}-minute session.
        </p>
      ) : (
        <div className="field">
          <label htmlFor="own-question">Add a question</label>
          <textarea
            id="own-question"
            rows={3}
            maxLength={QUESTION_MAX_LEN}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="row">
            <button type="button" className="btn btn--secondary" disabled={checking || !draft.trim()} onClick={() => void add()}>
              {checking ? "Checking the question" : "Check and add"}
            </button>
            <span className="muted small">
              {draft.length} of {QUESTION_MAX_LEN} characters
            </span>
          </div>
          <Notice notice={notice} />
        </div>
      )}
      <details className="section">
        <summary>Add from My questions</summary>
        {saved.isPending && <p className="muted small">Loading your saved questions</p>}
        {saved.data && saved.data.length === 0 && (
          <p className="muted small">
            No saved questions yet. Use “Save to My questions” on a question above, or go to{" "}
            <Link to="/questions/mine">My questions</Link>.
          </p>
        )}
        {savedLeft.length > 0 && (
          <ul className="plain-list saved-pick">
            {savedLeft.map((q) => (
              <li key={q.id} className="row row--between">
                <span>
                  {q.text} <span className="tag">{interviewTypeLabel[q.category]}</span>
                </span>
                <button
                  type="button"
                  className="btn btn--quiet"
                  disabled={atCap}
                  aria-label={`Add “${q.text}”`}
                  onClick={() => setNotice(setup.addSaved(q))}
                >
                  Add
                </button>
              </li>
            ))}
          </ul>
        )}
        {saved.data && saved.data.length > 0 && savedLeft.length === 0 && (
          <p className="muted small">Every saved question is in this interview.</p>
        )}
      </details>
    </section>
  );
}

function OwnQuestionItem({ setup, q }: { setup: CustomSetupState; q: OwnQuestion }) {
  const id = useId();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<CheckNotice | null>(null);
  const [busy, setBusy] = useState(false);
  const offCategory = !setup.chosen.includes(q.category);
  const addBlock = offCategory ? categoryBlock(q.category, setup.chosen, setup.duration) : null;

  const recategorize = async (category: StandardType) => {
    setBusy(true);
    setNotice(null);
    setNotice(await setup.recategorize(q.key, category));
    setBusy(false);
  };

  const save = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const row = await savedQuestionsApi.create({ text: q.text, category: q.category, competencies: q.competencies });
      setup.updateQuestion(q.key, { saved_question_id: row.id });
      void queryClient.invalidateQueries({ queryKey: keys.savedQuestions });
      setNotice({ tone: "warning", message: "Saved to My questions." });
    } catch (err) {
      setNotice(
        err instanceof ApiError && err.code === "duplicate_question"
          ? { tone: "warning", message: "This question is already in My questions." }
          : { tone: "error", message: err instanceof Error ? err.message : String(err) },
      );
    }
    setBusy(false);
  };

  return (
    <li className="own-question" data-testid="own-question">
      <p className="own-question__text">{q.text}</p>
      {q.duplicateOf && (
        <p className="hint" role="status">
          This looks a lot like “{q.duplicateOf}”.
        </p>
      )}
      <div className="row">
        <div className="field">
          <label htmlFor={`${id}-category`}>Kind of question</label>
          <select
            id={`${id}-category`}
            value={q.category}
            disabled={busy}
            aria-invalid={offCategory || undefined}
            onChange={(e) => void recategorize(e.target.value as StandardType)}
          >
            {offCategory && (
              <option value={q.category}>{interviewTypeLabel[q.category]} (not in this interview)</option>
            )}
            {setup.chosen.map((c) => (
              <option key={c} value={c}>
                {interviewTypeLabel[c]}
              </option>
            ))}
          </select>
        </div>
        <p className="muted small own-question__competencies">
          Scored on: {q.competencies.map(competencyLabel).join(", ")}
        </p>
      </div>
      {offCategory && (
        <div className="notice" role="status">
          <p>
            The interviewer tags this as {interviewTypeLabel[q.category]}, which is not in this interview.{" "}
            {addBlock ?? "Add it, or pick another kind above."}
          </p>
          {!addBlock && (
            <button type="button" className="btn btn--secondary" onClick={() => setup.toggleCategory(q.category)}>
              Add {interviewTypeLabel[q.category]}
            </button>
          )}
        </div>
      )}
      <div className="row">
        <label className="check">
          <input
            type="checkbox"
            checked={q.must_ask}
            onChange={(e) => setup.updateQuestion(q.key, { must_ask: e.target.checked })}
          />
          Must ask
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={q.verbatim}
            onChange={(e) => setup.updateQuestion(q.key, { verbatim: e.target.checked })}
          />
          Ask exactly as written
        </label>
      </div>
      <div className="row">
        {q.saved_question_id === null ? (
          <button type="button" className="btn btn--quiet" disabled={busy} onClick={() => void save()}>
            Save to My questions
          </button>
        ) : (
          <span className="muted small">In My questions</span>
        )}
        <button type="button" className="btn btn--quiet" onClick={() => setup.removeQuestion(q.key)}>
          Remove<span className="visually-hidden"> “{q.text}”</span>
        </button>
      </div>
      <Notice notice={notice} />
    </li>
  );
}
