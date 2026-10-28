import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import { savedQuestionsApi } from "../api/custom";
import { keys, useDebrief, useJob, useProgress } from "../api/hooks";
import type {
  CustomSessionSpec,
  Debrief,
  DebriefQuestion,
  DebriefSession,
  QuestionScore,
  Scorecard,
  StandardType,
  ValueScore,
} from "../api/types";
import { RealismRating } from "../components/RealismRating";
import { JobTrend } from "../components/TrendChart";
import { ErrorNotice, HireSignalScale, Loading, PageHead, Rubric } from "../components/ui";
import { CustomNext } from "../custom/CustomNext";
import { useRepeatSetup } from "../custom/repeat";
import { competencyLabel, difficultyLabel, formatDate, interviewTypeLabel, modeLabel } from "../labels";
import { useFeature } from "../theme/features";
import { DebriefV2 } from "./debrief/DebriefV2";
import { PracticeQuestions } from "./debrief/PracticeQuestions";
import { setupLink } from "./GapAnalysisPage";

export { weakestCompetencies } from "./debrief/PracticeQuestions";

/**
 * FB-1, FB-2, PR-2: hire signal and rationale, per-question rubric, company values, next session.
 * In generic mode there are no company values; the page says so instead of showing an empty table.
 * A 10-minute mini interview says how many questions the signal rests on, and that it is not
 * counted in the progress trends. L05: a one-question rating, "felt like a real interview".
 * With `v2_enabled` (FL-1) a ready debrief uses the v2 layout in ./debrief (DB-1, DB-2).
 */
export function DebriefPage() {
  const { sessionId = "" } = useParams();
  const debrief = useDebrief(sessionId);
  const v2 = useFeature("v2_enabled");

  if (debrief.isPending) return <Loading label="Loading the debrief" />;
  if (debrief.isError) return <ErrorNotice error={debrief.error} />;

  const { session, scorecard, next_session: next, status } = debrief.data;
  const config = session.config;
  const date = session.ended_at ?? session.started_at;

  // FL-1: the v2 debrief replaces the ready view only; the waiting states stay as they are.
  if (v2 && status === "ready" && scorecard) {
    return (
      <DebriefV2
        debrief={debrief.data}
        scorecard={scorecard}
        sideExtra={config.custom && <CustomActions session={session} custom={config.custom} />}
      />
    );
  }

  return (
    <>
      <Breadcrumb jobId={session.job_target_id} company={debrief.data.company_name} />
      <PageHead title="Debrief">
        <p>
          {interviewTypeLabel[config.interview_type]} interview, {difficultyLabel[config.difficulty]} difficulty,{" "}
          {modeLabel[config.mode]} mode, {session.minutes_billed} minutes
          {date && `, ${formatDate(date)}`}
        </p>
        {/* TR-1 (S13): behind v2_enabled until launch. */}
        {v2 && session.ended_at && (
          <p>
            <Link to={`/sessions/${session.id}/transcript`}>Read the transcript</Link>
          </p>
        )}
      </PageHead>
      {status === "not_ended" && (
        <section className="section panel" data-testid="not-ended">
          <p>This interview has not finished, so there is nothing to score yet.</p>
          <Link className="btn" to={`/sessions/${session.id}/live`}>
            Go to the interview
          </Link>
        </section>
      )}
      {status === "not_started" && (
        <section className="section panel" data-testid="not-started">
          <p>
            {session.failure_reason ??
              "This interview did not start, so there is nothing to score. Nothing was counted or billed."}
          </p>
          <Link className="btn" to={setupLink(session.job_target_id)}>
            Set up another session
          </Link>
        </section>
      )}
      {status === "scoring" && <Loading label="Scoring your interview. The debrief is usually ready within a minute." />}
      {status === "failed" && <ErrorNotice error="Scoring failed. Your minutes for this session are refunded." />}
      {status === "ready" && (
        <div className="with-side">
          {scorecard ? (
            <ScorecardView
              scorecard={scorecard}
              coach={config.mode === "coach"}
              mini={config.duration_min === 10}
              values={valuesInfo(debrief.data)}
              questions={debrief.data.questions}
              custom={config.custom}
            />
          ) : (
            <div />
          )}
          <aside className="side-column" aria-label="What to do next">
            <RealismRating sessionId={session.id} />
            {config.custom && <CustomActions session={session} custom={config.custom} />}
            <section className="next-card" aria-labelledby="next-heading">
              <h2 id="next-heading" className="next-card__tag">
                Next rehearsal
              </h2>
              {debrief.data.next_custom_session ? (
                <CustomNext jobId={session.job_target_id} rec={debrief.data.next_custom_session} />
              ) : next ? (
                <>
                  <p>
                    <strong>
                      {interviewTypeLabel[next.interview_type]}, {difficultyLabel[next.difficulty]}
                    </strong>
                    : {next.focus_topics.join(", ")}. {next.reason}
                  </p>
                  <Link className="btn" to={setupLink(session.job_target_id, next)}>
                    Start this rehearsal
                  </Link>
                </>
              ) : (
                <Link className="btn" to={setupLink(session.job_target_id)}>
                  Set up another session
                </Link>
              )}
            </section>
            <PracticeQuestions debrief={debrief.data} />
            <SideTrends jobId={session.job_target_id} />
          </aside>
        </div>
      )}
    </>
  );
}

/**
 * CU-9: run the same Custom setup again (the setup screen opens prefilled), and CU-8: save the
 * session's own questions that are not in "My questions" yet.
 */
function CustomActions({ session, custom }: { session: DebriefSession; custom: CustomSessionSpec }) {
  const queryClient = useQueryClient();
  const repeat = useRepeatSetup();
  const unsaved = custom.questions.filter((q) => q.saved_question_id === null);
  const save = useMutation({
    mutationFn: async () => {
      let saved = 0;
      let already = 0;
      for (const q of unsaved) {
        try {
          await savedQuestionsApi.create({ text: q.text, category: q.category, competencies: q.competencies });
          saved += 1;
        } catch (err) {
          if (err instanceof ApiError && err.code === "duplicate_question") already += 1;
          else throw err;
        }
      }
      return { saved, already };
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: keys.savedQuestions }),
  });
  const own = custom.questions.length;

  return (
    <section className="side-panel" aria-labelledby="custom-actions-heading">
      <h2 id="custom-actions-heading">Your setup</h2>
      <p className="muted small">
        {custom.categories.map((c) => interviewTypeLabel[c.category]).join(", ")}.{" "}
        {own === 1 ? "1 of your questions." : `${own} of your questions.`}
      </p>
      <div className="stack">
        <button type="button" className="btn" disabled={repeat.isPending} onClick={() => repeat.mutate(session.id)}>
          Run this setup again
        </button>
        {unsaved.length > 0 && (
          <button
            type="button"
            className="btn btn--secondary"
            disabled={save.isPending || save.isSuccess}
            onClick={() => save.mutate()}
          >
            Save my questions
          </button>
        )}
      </div>
      {repeat.isError && <ErrorNotice error={repeat.error} />}
      {save.isError && <ErrorNotice error={save.error} />}
      {save.data && (
        <p className="muted small" role="status" data-testid="saved-result">
          {save.data.saved === 1 ? "Saved 1 question" : `Saved ${save.data.saved} questions`} to{" "}
          <Link to="/questions/mine">My questions</Link>.
          {save.data.already > 0 && ` ${save.data.already} ${save.data.already === 1 ? "was" : "were"} already there.`}
        </p>
      )}
    </section>
  );
}

/** "Interview rehearsals / job title, company / Debrief". The job name is extra: the page works without it. */
function Breadcrumb({ jobId, company }: { jobId: string; company: string | null }) {
  const job = useJob(jobId, false);
  const posting = job.data?.posting;
  const name = posting ? `${posting.title}, ${posting.company_name ?? company ?? ""}`.replace(/, $/, "") : company;
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol>
        <li>
          <Link to="/">Interview rehearsals</Link>
        </li>
        {name && <li>{name}</li>}
        <li aria-current="page">Debrief</li>
      </ol>
    </nav>
  );
}

/** PR-1 for this job, compact. Hidden until there is at least one Realistic session. */
function SideTrends({ jobId }: { jobId: string }) {
  const progress = useProgress(jobId);
  if (!progress.data || progress.data.snapshots.length === 0) return null;
  return (
    <section className="side-panel" aria-labelledby="side-trends-heading">
      <h2 id="side-trends-heading">Competencies over time</h2>
      <p className="muted small">Realistic sessions for this job.</p>
      <JobTrend jobId={jobId} />
    </section>
  );
}

interface ValuesInfo {
  generic: boolean;
  company: string | null;
  framework: string | null;
}

function valuesInfo(d: Debrief): ValuesInfo {
  return { generic: d.generic_mode, company: d.company_name, framework: d.values_framework };
}

/** Average of the competency scores for one question, on the 1 to 4 rubric. */
function questionAverage(q: QuestionScore): number | null {
  if (q.scores.length === 0) return null;
  return q.scores.reduce((sum, s) => sum + s.score, 0) / q.scores.length;
}

/** Bar color for a 1 to 4 score. Display only: the hire signal rules live in the scorer. */
function scoreTone(score: number): "strong" | "positive" | "neutral" | "negative" {
  if (score >= 3.5) return "strong";
  if (score >= 3) return "positive";
  if (score >= 2) return "neutral";
  return "negative";
}

function ScorecardView({
  scorecard,
  coach,
  mini,
  values,
  questions: planned = [],
  custom = null,
}: {
  scorecard: Scorecard;
  coach: boolean;
  mini: boolean;
  values: ValuesInfo;
  questions?: DebriefQuestion[];
  custom?: CustomSessionSpec | null;
}) {
  const byRef = new Map(planned.map((q) => [q.question_ref, q]));
  const questions = scorecard.per_question.length;
  return (
    <div className="stack">
      <section className="verdict" aria-labelledby="signal-heading">
        <h2 id="signal-heading" className="visually-hidden">
          Hire signal
        </h2>
        <HireSignalScale signal={scorecard.hire_signal} />
        <p>{scorecard.rationale}</p>
        {mini && (
          <p className="notice" data-testid="mini-note">
            Mini interview. Based on {questions} {questions === 1 ? "question" : "questions"}. Practice signal only.
            It is not counted in your progress trends.
          </p>
        )}
        {coach && <p className="muted">Coach sessions are not counted in your progress trends.</p>}
      </section>

      <section aria-labelledby="questions-heading">
        <h2 id="questions-heading">Question by question</h2>
        {custom ? (
          groupByCategory(scorecard.per_question, byRef, custom).map((group) => (
            <section key={group.key} aria-labelledby={`group-${group.key}`} data-testid={`group-${group.key}`}>
              <h3 id={`group-${group.key}`} className="question-group__title">
                {group.title}
              </h3>
              <ol className="plain-list question-list">
                {group.items.map((q) => (
                  <QuestionCard key={q.question_ref} q={q} plan={byRef.get(q.question_ref)} canSave />
                ))}
              </ol>
            </section>
          ))
        ) : (
          <ol className="plain-list question-list">
            {scorecard.per_question.map((q) => (
              <QuestionCard key={q.question_ref} q={q} plan={byRef.get(q.question_ref)} />
            ))}
          </ol>
        )}
      </section>

      <section className="panel" aria-labelledby="comp-heading">
        <h2 id="comp-heading">Competencies</h2>
        <table>
          <thead>
            <tr>
              <th scope="col">Competency</th>
              <th scope="col">Score</th>
              <th scope="col">Why</th>
            </tr>
          </thead>
          <tbody>
            {scorecard.competency_scores.map((c) => (
              <tr key={c.competency}>
                <td>{competencyLabel(c.competency)}</td>
                <td>
                  <Rubric score={c.score} />
                </td>
                <td>
                  {c.justification}
                  {c.quotes.map((q) => (
                    <blockquote key={q} className="quote">
                      “{q}”
                    </blockquote>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <ValuesSection scores={scorecard.value_scores} info={values} />
    </div>
  );
}

interface QuestionGroup {
  key: string;
  title: string;
  items: QuestionScore[];
}

/**
 * CU-6: a Custom session's breakdown by kind of question, in the order the candidate set. A
 * question the plan does not list (or with no category) goes under "Other questions".
 */
function groupByCategory(
  scores: QuestionScore[],
  byRef: Map<string, DebriefQuestion>,
  custom: CustomSessionSpec,
): QuestionGroup[] {
  const order: StandardType[] = custom.categories.map((c) => c.category);
  const groups: QuestionGroup[] = order.map((c) => ({ key: c, title: interviewTypeLabel[c], items: [] }));
  const other: QuestionGroup = { key: "other", title: "Other questions", items: [] };
  for (const q of scores) {
    const category = byRef.get(q.question_ref)?.category ?? null;
    const group = category ? groups.find((g) => g.key === category) : undefined;
    (group ?? other).items.push(q);
  }
  return [...groups, other].filter((g) => g.items.length > 0);
}

/** FB-2: one question with its average score, what was strong, what was missing, and the scores behind it. */
function QuestionCard({ q, plan, canSave = false }: { q: QuestionScore; plan?: DebriefQuestion; canSave?: boolean }) {
  const avg = questionAverage(q);
  const own = plan?.source === "candidate";
  // CU-9: an interviewer question of a Custom session can be kept for a later setup.
  const savable = canSave && plan?.source === "planner" && plan.category !== null && plan.competencies.length > 0;
  return (
    <li className="question-card" data-own={own || undefined}>
      <div className="question-card__head">
        <h3>
          {q.question_text}
          {own && (
            <>
              {" "}
              <span className="badge-own">Your question</span>
            </>
          )}
        </h3>
        {avg !== null && <span className="score-mono">{avg.toFixed(1)} / 4</span>}
      </div>
      {savable && plan && <SaveQuestion plan={plan} />}
      {avg !== null && (
        <div className="score-bar" data-tone={scoreTone(avg)} aria-hidden="true">
          <span style={{ width: `${(avg / 4) * 100}%` }} />
        </div>
      )}
      <div className="grid-2">
        <div>
          <h4>What was strong</h4>
          <ul>
            {q.strengths.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>What was missing</h4>
          <ul>
            {q.misses.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      </div>
      <details>
        <summary>Scores by competency</summary>
        <ul className="plain-list section">
          {q.scores.map((s) => (
            <li key={s.competency}>
              <div className="row">
                <span>{competencyLabel(s.competency)}</span>
                <Rubric score={s.score} />
              </div>
              <p className="muted">{s.justification}</p>
            </li>
          ))}
          {q.value_scores.map((v) => (
            <li key={`value-${v.value}`}>
              <div className="row">
                <span>
                  {v.value} <span className="muted">(company value)</span>
                </span>
                <Rubric score={v.score} />
              </div>
              <p className="muted">{v.justification}</p>
            </li>
          ))}
        </ul>
      </details>
    </li>
  );
}

const MAX_SAVED_COMPETENCIES = 3;

/**
 * CU-9: "Save to My questions" for an interviewer question, with its category and competencies.
 * The interviewer's questions are drawn fresh when a setup runs again, so this keeps a good one.
 */
function SaveQuestion({ plan }: { plan: DebriefQuestion }) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: async () => {
      try {
        await savedQuestionsApi.create({
          text: plan.text,
          category: plan.category as StandardType,
          competencies: plan.competencies.slice(0, MAX_SAVED_COMPETENCIES),
        });
        return "saved" as const;
      } catch (err) {
        if (err instanceof ApiError && err.code === "duplicate_question") return "already" as const;
        throw err;
      }
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: keys.savedQuestions }),
  });
  return (
    <div className="row">
      {save.data ? (
        <p className="muted small" role="status">
          {save.data === "saved" ? "Saved to " : "Already in "}
          <Link to="/questions/mine">My questions</Link>.
        </p>
      ) : (
        <button
          type="button"
          className="btn btn--quiet"
          disabled={save.isPending}
          onClick={() => save.mutate()}
          aria-label={`Save to My questions: ${plan.text}`}
        >
          Save to My questions
        </button>
      )}
      {save.isError && <ErrorNotice error={save.error} />}
    </div>
  );
}

/** Company values (IV-5). Generic mode has none, and the page says so in words. */
function ValuesSection({ scores, info }: { scores: ValueScore[]; info: ValuesInfo }) {
  const title = info.framework ?? "Company values";
  if (info.generic || scores.length === 0) {
    return (
      <section className="panel" aria-labelledby="values-heading">
        <h2 id="values-heading">Company values</h2>
        <p className="muted" data-testid="values-generic">
          {info.generic
            ? "This interview used the general interview style, with no company profile. Company values are not scored."
            : "No company value was scored in this interview."}
        </p>
      </section>
    );
  }
  return (
    <section className="panel" aria-labelledby="values-heading">
      <h2 id="values-heading">{title}</h2>
      <p className="muted">
        How your answers showed the values {info.company ?? "the company"} hires for. They count toward the hire signal.
      </p>
      <table>
        <thead>
          <tr>
            <th scope="col">Value</th>
            <th scope="col">Score</th>
            <th scope="col">Why</th>
          </tr>
        </thead>
        <tbody>
          {scores.map((v) => (
            <tr key={v.value}>
              <td>{v.value}</td>
              <td>
                <Rubric score={v.score} />
              </td>
              <td>
                {v.justification}
                {v.quotes.map((q) => (
                  <blockquote key={q} className="quote">
                    “{q}”
                  </blockquote>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
