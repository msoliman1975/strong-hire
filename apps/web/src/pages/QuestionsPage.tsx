import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { useBankCompanies, useQuestions } from "../api/hooks";
import { COMPETENCIES_BY_TYPE, GENERAL, type QuestionFilter } from "../api/questions";
import type { BankQuestion, Competency, InterviewType, Level, RoleFamily, StandardType } from "../api/types";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { competencyLabel, interviewTypeLabel, levelLabel, roleFamilyLabel } from "../labels";

/** The four question categories; Custom is a session type, not a category (CU-1). */
const TYPES = (Object.keys(interviewTypeLabel) as InterviewType[]).filter((t): t is StandardType => t !== "custom");
const ROLES = Object.keys(roleFamilyLabel) as RoleFamily[];
const LEVELS = Object.keys(levelLabel) as Level[];
const ALL_AREAS = new Set<string>(Object.values(COMPETENCIES_BY_TYPE).flat());

function pick<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return allowed.includes(value as T) ? (value as T) : null;
}

/**
 * QB-1 to QB-3: the question bank with key hints. Filters live in the URL (company, type, area,
 * role, level, q), so the debrief can link to a filtered view (QB-4).
 */
export function QuestionsPage() {
  const [params, setParams] = useSearchParams();
  const filter: QuestionFilter = {
    company: params.get("company") || null,
    interviewType: pick(params.get("type"), TYPES),
    competencies: params.getAll("area").filter((a): a is Competency => ALL_AREAS.has(a)),
    roleFamily: pick(params.get("role"), ROLES),
    level: pick(params.get("level"), LEVELS),
    text: params.get("q"),
  };
  const companies = useBankCompanies();
  const questions = useQuestions(filter);

  const update = (change: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(params);
    change(next);
    setParams(next, { replace: true });
  };
  const setOne = (name: string, value: string) =>
    update((next) => {
      if (value) next.set(name, value);
      else next.delete(name);
    });
  const setType = (value: string) =>
    update((next) => {
      if (value) next.set("type", value);
      else next.delete("type");
      // Areas belong to an interview type; keep only the ones the new type has.
      const keep = value ? COMPETENCIES_BY_TYPE[value as StandardType] : [];
      const areas = next.getAll("area").filter((a) => keep.includes(a as Competency));
      next.delete("area");
      for (const a of areas) next.append("area", a);
    });
  const toggleArea = (area: Competency, on: boolean) =>
    update((next) => {
      const areas = next.getAll("area").filter((a) => a !== area);
      if (on) areas.push(area);
      next.delete("area");
      for (const a of areas) next.append("area", a);
    });

  const filtered = [...params.keys()].length > 0;
  const companyName = questions.data?.company?.name;

  return (
    <>
      <PageHead title="Questions">
        <p>Interview questions with key hints on what each one is looking for.</p>
      </PageHead>
      <section className="panel section" aria-label="Filters">
        <div className="row">
          <div className="field">
            <label htmlFor="q-company">Company</label>
            <select id="q-company" value={filter.company ?? ""} onChange={(e) => setOne("company", e.target.value)}>
              <option value="">All companies</option>
              <option value={GENERAL}>General questions</option>
              {(companies.data ?? []).map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="q-type">Interview type</label>
            <select id="q-type" value={filter.interviewType ?? ""} onChange={(e) => setType(e.target.value)}>
              <option value="">All types</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {interviewTypeLabel[t]}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="q-role">Job category</label>
            <select id="q-role" value={filter.roleFamily ?? ""} onChange={(e) => setOne("role", e.target.value)}>
              <option value="">All job categories</option>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {roleFamilyLabel[r]}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="q-level">Level</label>
            <select id="q-level" value={filter.level ?? ""} onChange={(e) => setOne("level", e.target.value)}>
              <option value="">All levels</option>
              {LEVELS.map((l) => (
                <option key={l} value={l}>
                  {levelLabel[l]}
                </option>
              ))}
            </select>
          </div>
          <SearchField value={filter.text ?? ""} onChange={(v) => setOne("q", v)} />
        </div>
        <fieldset className="field">
          <legend>Question area</legend>
          {filter.interviewType ? (
            <div className="row">
              {COMPETENCIES_BY_TYPE[filter.interviewType].map((c) => (
                <label key={c} className="check">
                  <input
                    type="checkbox"
                    checked={filter.competencies?.includes(c) ?? false}
                    onChange={(e) => toggleArea(c, e.target.checked)}
                  />
                  {competencyLabel(c)}
                </label>
              ))}
            </div>
          ) : (
            <p className="hint">Pick an interview type to filter by area.</p>
          )}
        </fieldset>
        {filtered && (
          <button type="button" className="btn btn--quiet" onClick={() => setParams(new URLSearchParams(), { replace: true })}>
            Clear filters
          </button>
        )}
      </section>
      {questions.isPending && <Loading label="Loading questions" />}
      {questions.isError && <ErrorNotice error={questions.error} />}
      {questions.data && (
        <>
          {filter.company !== GENERAL && (
            <QuestionSection
              title={companyName ? `${companyName} questions` : "Company questions"}
              questions={questions.data.company_questions}
              showCompany={!companyName}
            />
          )}
          <QuestionSection
            title={filter.company && filter.company !== GENERAL ? "Also common" : "General questions"}
            note={
              filter.company && filter.company !== GENERAL
                ? "Questions many companies ask, matching the same filters."
                : undefined
            }
            questions={questions.data.general_questions}
          />
        </>
      )}
    </>
  );
}

/** Text search. Updates the URL after a short pause, not on every key. */
function SearchField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value);
  // When the URL changes from outside (Clear filters, a link), show its text.
  const [shown, setShown] = useState(value);
  if (value !== shown) {
    setShown(value);
    setText(value);
  }
  useEffect(() => {
    if (text === value) return;
    const t = setTimeout(() => onChange(text), 300);
    return () => clearTimeout(t);
  }, [text, value, onChange]);
  return (
    <div className="field">
      <label htmlFor="q-search">Search</label>
      <input id="q-search" type="search" value={text} onChange={(e) => setText(e.target.value)} />
    </div>
  );
}

function QuestionSection({
  title,
  note,
  questions,
  showCompany = false,
}: {
  title: string;
  note?: string;
  questions: BankQuestion[];
  showCompany?: boolean;
}) {
  const id = `questions-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section className="section" aria-labelledby={id}>
      <h2 id={id}>
        {title} <span className="muted">({questions.length})</span>
      </h2>
      {note && <p className="muted">{note}</p>}
      {questions.length === 0 ? (
        <p className="muted">No questions match these filters.</p>
      ) : (
        <ul className="question-list plain-list">
          {questions.map((q) => (
            <BankQuestionCard key={q.id} q={q} showCompany={showCompany} />
          ))}
        </ul>
      )}
    </section>
  );
}

/** QB-2: the question, its tags and key hints. No model answer. */
function BankQuestionCard({ q, showCompany }: { q: BankQuestion; showCompany: boolean }) {
  return (
    <li className="question-card">
      <h3>{q.question}</h3>
      <div className="row" aria-label="Tags">
        {showCompany && q.company_name && <span className="tag">{q.company_name}</span>}
        <span className="tag">{interviewTypeLabel[q.interview_type]}</span>
        {q.competencies.map((c) => (
          <span key={c} className="tag">
            {competencyLabel(c)}
          </span>
        ))}
        {q.role_families.map((r) => (
          <span key={r} className="tag">
            {roleFamilyLabel[r]}
          </span>
        ))}
        {q.levels.map((l) => (
          <span key={l} className="tag">
            {levelLabel[l]}
          </span>
        ))}
      </div>
      {q.hints ? (
        <>
          <div>
            <h4>What it is looking for</h4>
            <ul>
              {q.hints.looking_for.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          </div>
          <details>
            <summary>Strong signals and watch-outs</summary>
            <div className="grid-2">
              <div>
                <h4>Strong signals</h4>
                <ul>
                  {q.hints.strong_signals.map((h) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h4>Watch-outs</h4>
                <ul>
                  {q.hints.watch_outs.map((h) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              </div>
            </div>
          </details>
        </>
      ) : (
        <p className="muted small">Hints for this question are coming soon.</p>
      )}
      {q.values.length > 0 && <p className="muted small">Company values: {q.values.join(", ")}</p>}
      {q.source_url && (
        <p className="small">
          <a href={q.source_url} target="_blank" rel="noreferrer noopener">
            Where this question was reported
          </a>
        </p>
      )}
    </li>
  );
}
