import { Link, useParams } from "react-router";

import { useDebrief } from "../api/hooks";
import type { Scorecard } from "../api/types";
import { ErrorNotice, HireSignalScale, Loading, PageHead, Rubric } from "../components/ui";
import { competencyLabel, difficultyLabel, interviewTypeLabel, modeLabel } from "../labels";
import { setupLink } from "./GapAnalysisPage";

/** FB-1, FB-2, PR-2: hire signal and rationale, per-question rubric, next session. */
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
      {status === "ready" && scorecard && <ScorecardView scorecard={scorecard} coach={config.mode === "coach"} />}
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

function ScorecardView({ scorecard, coach }: { scorecard: Scorecard; coach: boolean }) {
  return (
    <div className="stack">
      <section className="verdict" aria-labelledby="signal-heading">
        <h2 id="signal-heading" className="muted">
          Hire signal
        </h2>
        <HireSignalScale signal={scorecard.hire_signal} />
        <p>{scorecard.rationale}</p>
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
