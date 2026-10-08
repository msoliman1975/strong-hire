import { Link, useParams } from "react-router";

import { useDebrief } from "../api/hooks";
import type { Debrief, Scorecard, ValueScore } from "../api/types";
import { ErrorNotice, HireSignalScale, Loading, PageHead, Rubric } from "../components/ui";
import { competencyLabel, difficultyLabel, interviewTypeLabel, modeLabel } from "../labels";
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

  return (
    <div className="page--narrow">
      <PageHead title="Debrief">
        <p>
          {interviewTypeLabel[config.interview_type]} interview, {difficultyLabel[config.difficulty]} difficulty,{" "}
          {modeLabel[config.mode]} mode, {session.minutes_billed} minutes
        </p>
      </PageHead>
      {status === "scoring" && <Loading label="Scoring your interview. The debrief is usually ready within a minute." />}
      {status === "failed" && <ErrorNotice error="Scoring failed. Your minutes for this session are refunded." />}
      {status === "ready" && scorecard && (
        <ScorecardView
          scorecard={scorecard}
          coach={config.mode === "coach"}
          mini={config.duration_min === 10}
          values={valuesInfo(debrief.data)}
        />
      )}
      {status === "ready" && (
        <section className="section panel" aria-labelledby="next-heading">
          <h2 id="next-heading">Next session</h2>
          {next ? (
            <>
              <p>
                <strong>
                  {interviewTypeLabel[next.interview_type]}, {difficultyLabel[next.difficulty]}
                </strong>
                : {next.focus_topics.join(", ")}. {next.reason}
              </p>
              <Link className="btn" to={setupLink(session.job_target_id, next)}>
                Set up the next session
              </Link>
            </>
          ) : (
            <Link className="btn" to={setupLink(session.job_target_id)}>
              Set up another session
            </Link>
          )}
        </section>
      )}
    </div>
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
        <h2 id="signal-heading" className="muted">
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

      <section className="panel" aria-labelledby="questions-heading">
        <h2 id="questions-heading">Question by question</h2>
        {scorecard.per_question.map((q, i) => (
          <details key={q.question_ref} open={i === 0}>
            <summary>
              <strong>{q.question_text}</strong>
            </summary>
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
            <div className="grid-2">
              <div>
                <h3>What was strong</h3>
                <ul>
                  {q.strengths.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h3>What was missing</h3>
                <ul>
                  {q.misses.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </div>
            </div>
          </details>
        ))}
      </section>
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
