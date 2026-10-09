import { Link, useParams } from "react-router";

import { useDebrief, useJob, useProgress } from "../api/hooks";
import type { Debrief, QuestionScore, Scorecard, ValueScore } from "../api/types";
import { CompetencySparklines } from "../components/TrendChart";
import { ErrorNotice, HireSignalScale, Loading, PageHead, Rubric } from "../components/ui";
import { competencyLabel, difficultyLabel, formatDate, interviewTypeLabel, modeLabel } from "../labels";
import { setupLink } from "./GapAnalysisPage";

/**
 * FB-1, FB-2, PR-2: hire signal and rationale, per-question rubric, company values, next session.
 * In generic mode there are no company values; the page says so instead of showing an empty table.
 * A 10-minute mini interview says how many questions the signal rests on, and that it is not
 * counted in the progress trends.
 */
export function DebriefPage() {
  const { sessionId = "" } = useParams();
  const debrief = useDebrief(sessionId);

  if (debrief.isPending) return <Loading label="Loading the debrief" />;
  if (debrief.isError) return <ErrorNotice error={debrief.error} />;

  const { session, scorecard, next_session: next, status } = debrief.data;
  const config = session.config;
  const date = session.ended_at ?? session.started_at;

  return (
    <>
      <Breadcrumb jobId={session.job_target_id} company={debrief.data.company_name} />
      <PageHead title="Debrief">
        <p>
          {interviewTypeLabel[config.interview_type]} interview, {difficultyLabel[config.difficulty]} difficulty,{" "}
          {modeLabel[config.mode]} mode, {session.minutes_billed} minutes
          {date && `, ${formatDate(date)}`}
        </p>
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
            />
          ) : (
            <div />
          )}
          <aside className="side-column" aria-label="What to do next">
            <section className="next-card" aria-labelledby="next-heading">
              <h2 id="next-heading" className="next-card__tag">
                Next rehearsal
              </h2>
              {next ? (
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
            <SideTrends jobId={session.job_target_id} />
          </aside>
        </div>
      )}
    </>
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
      <CompetencySparklines snapshots={progress.data.snapshots} />
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
}: {
  scorecard: Scorecard;
  coach: boolean;
  mini: boolean;
  values: ValuesInfo;
}) {
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
        <ol className="plain-list question-list">
          {scorecard.per_question.map((q) => (
            <QuestionCard key={q.question_ref} q={q} />
          ))}
        </ol>
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

/** FB-2: one question with its average score, what was strong, what was missing, and the scores behind it. */
function QuestionCard({ q }: { q: QuestionScore }) {
  const avg = questionAverage(q);
  return (
    <li className="question-card">
      <div className="question-card__head">
        <h3>{q.question_text}</h3>
        {avg !== null && <span className="score-mono">{avg.toFixed(1)} / 4</span>}
      </div>
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
