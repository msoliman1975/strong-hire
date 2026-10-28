import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { customApi, questionRefusal, savedQuestionsApi } from "../api/custom";
import { keys, useSavedQuestions } from "../api/hooks";
import type { SavedQuestion, StandardType } from "../api/types";
import { QuestionBankTabs, useQuestionBankTitle } from "../components/QuestionBankTabs";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { CATEGORIES, QUESTION_MAX_LEN } from "../custom/rules";
import { checkErrorMessage } from "../custom/useCustomSetup";
import { competencyLabel, formatDate, interviewTypeLabel } from "../labels";

/**
 * Checks a question with the CU-5 check (optionally in a chosen category) and returns its tag,
 * or throws with the refusal reason.
 */
/**
 * The reason to show next to the question for a 422 `question_refused` from the server's own
 * check of a saved question (CU-5), else null.
 */
function refusedReason(err: unknown): string | null {
  return questionRefusal(err)?.reason ?? null;
}

function RefusalOrError({ error, id }: { error: unknown; id: string }) {
  const reason = refusedReason(error);
  return reason ? (
    <p className="field-error" id={id} role="alert" data-testid="saved-refused">
      {reason}
    </p>
  ) : (
    <ErrorNotice error={error} />
  );
}

async function checked(text: string, category?: StandardType) {
  let result;
  try {
    result = await customApi.check({ text, kind: "question", category: category ?? null });
  } catch (err) {
    throw new Error(checkErrorMessage(err), { cause: err });
  }
  if (!result.accepted || !result.category) throw new Error(result.reason);
  return { category: result.category, competencies: result.competencies };
}

/**
 * CU-8: "My questions", the saved list. Add (checked and tagged first, CU-5), edit the text or
 * the kind of question, delete. Each one can be added to a Custom interview from its setup.
 */
export function MyQuestionsPage() {
  const title = useQuestionBankTitle("My questions");
  const saved = useSavedQuestions();
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: keys.savedQuestions });
  const [draft, setDraft] = useState("");

  const add = useMutation({
    mutationFn: async (text: string) => {
      const tag = await checked(text);
      return savedQuestionsApi.create({ text, ...tag });
    },
    onSuccess: () => {
      setDraft("");
      refresh();
    },
  });

  return (
    <div className="page--narrow">
      <PageHead title={title}>
        <p>
          Questions you want to practice, for example ones a recruiter warned you about. Add them to a Custom interview
          when you set one up.
        </p>
      </PageHead>
      <QuestionBankTabs />
      <section className="panel" aria-labelledby="add-saved-heading">
        <h2 id="add-saved-heading">Add a question</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim()) add.mutate(draft.trim());
          }}
        >
          <div className="field">
            <label htmlFor="saved-new">Question</label>
            <p className="hint" id="saved-new-hint">
              We check it is an interview question and tag it with a kind of question and what it is scored on.
            </p>
            <textarea
              id="saved-new"
              rows={3}
              maxLength={QUESTION_MAX_LEN}
              aria-describedby={refusedReason(add.error) ? "saved-new-hint saved-new-error" : "saved-new-hint"}
              aria-invalid={refusedReason(add.error) ? true : undefined}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          </div>
          {add.isError && <RefusalOrError error={add.error} id="saved-new-error" />}
          <button type="submit" className="btn" disabled={add.isPending || !draft.trim()}>
            {add.isPending ? "Checking the question" : "Check and save"}
          </button>
        </form>
      </section>
      <section className="section" aria-labelledby="saved-list-heading">
        <h2 id="saved-list-heading">Saved questions</h2>
        {saved.isPending && <Loading label="Loading your questions" />}
        {saved.isError && <ErrorNotice error={saved.error} />}
        {saved.data && saved.data.length === 0 && <p className="muted">No saved questions yet.</p>}
        {saved.data && saved.data.length > 0 && (
          <ul className="plain-list own-question-list" aria-label="Saved questions">
            {saved.data.map((q) => (
              <SavedItem key={q.id} q={q} onChange={refresh} />
            ))}
          </ul>
        )}
      </section>
      <p className="muted">
        <Link to="/account">Back to your account</Link>
      </p>
    </div>
  );
}

function SavedItem({ q, onChange }: { q: SavedQuestion; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(q.text);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const update = useMutation({
    mutationFn: async (patch: { text?: string; category?: StandardType }) => {
      const nextText = patch.text ?? q.text;
      // A new text or kind is checked and tagged again, so the competencies fit (CU-3).
      const tag = await checked(nextText, patch.category ?? q.category);
      return savedQuestionsApi.update(q.id, {
        ...(patch.text !== undefined ? { text: nextText } : {}),
        category: tag.category,
        competencies: tag.competencies,
      });
    },
    onSuccess: () => {
      setEditing(false);
      onChange();
    },
  });
  const remove = useMutation({ mutationFn: () => savedQuestionsApi.remove(q.id), onSuccess: onChange });

  return (
    <li className="own-question" data-testid="saved-question">
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) update.mutate({ text: text.trim() });
          }}
        >
          <div className="field">
            <label htmlFor={`edit-${q.id}`}>Question</label>
            <textarea
              id={`edit-${q.id}`}
              rows={3}
              maxLength={QUESTION_MAX_LEN}
              aria-invalid={refusedReason(update.error) ? true : undefined}
              aria-describedby={refusedReason(update.error) ? `edit-${q.id}-error` : undefined}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
          <div className="row">
            <button type="submit" className="btn" disabled={update.isPending || !text.trim()}>
              Save
            </button>
            <button
              type="button"
              className="btn btn--quiet"
              onClick={() => {
                setEditing(false);
                setText(q.text);
                update.reset();
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <p className="own-question__text">{q.text}</p>
      )}
      <div className="row">
        <div className="field">
          <label htmlFor={`kind-${q.id}`}>Kind of question</label>
          <select
            id={`kind-${q.id}`}
            value={q.category}
            disabled={update.isPending}
            onChange={(e) => update.mutate({ category: e.target.value as StandardType })}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {interviewTypeLabel[c]}
              </option>
            ))}
          </select>
        </div>
        <p className="muted small own-question__competencies">
          Scored on: {q.competencies.map(competencyLabel).join(", ")}. Saved {formatDate(q.created_at)}.
        </p>
      </div>
      {update.isError && <RefusalOrError error={update.error} id={`edit-${q.id}-error`} />}
      {remove.isError && <ErrorNotice error={remove.error} />}
      <div className="row">
        {!editing && (
          <button type="button" className="btn btn--quiet" onClick={() => setEditing(true)}>
            Edit<span className="visually-hidden"> “{q.text}”</span>
          </button>
        )}
        {confirmDelete ? (
          <>
            <span>Delete this question?</span>
            <button type="button" className="btn btn--danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
              Delete
            </button>
            <button type="button" className="btn btn--quiet" onClick={() => setConfirmDelete(false)}>
              Keep it
            </button>
          </>
        ) : (
          <button type="button" className="btn btn--quiet" onClick={() => setConfirmDelete(true)}>
            Delete<span className="visually-hidden"> “{q.text}”</span>
          </button>
        )}
      </div>
    </li>
  );
}
