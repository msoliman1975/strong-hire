/**
 * AD-5, RS-2: the brief the interviewer worked from and the rubric the scorer used, on the
 * session and replay pages. The API sends the brief only under the transcript's consent rule.
 */
import type { AdminSessionSetup, BriefView } from "../api/part3";
import { sentence } from "../format";

export function SessionSetupPanel({ setup }: { setup: AdminSessionSetup | null | undefined }) {
  if (!setup) return null;
  const brief = (setup.brief ?? null) as BriefView | null;
  const rubric = setup.rubric;
  const questions = [...(brief?.questions ?? [])].sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0));
  return (
    <section className="section" aria-labelledby="session-setup">
      <h2 id="session-setup">Brief and rubric</h2>
      {brief ? (
        <div className="panel">
          <h3>Brief</h3>
          <dl className="dl">
            <dt>Skills tested</dt>
            <dd>{(brief.target_competencies ?? []).map(sentence).join(", ") || "-"}</dd>
            {brief.persona && (
              <>
                <dt>Interviewer</dt>
                <dd>
                  {brief.persona.tone}
                  {brief.persona.pushback_style ? `; ${brief.persona.pushback_style}` : ""}
                </dd>
              </>
            )}
            {brief.seniority_bar && (
              <>
                <dt>Bar at this level</dt>
                <dd>{brief.seniority_bar}</dd>
              </>
            )}
            {(brief.probe_areas ?? []).length > 0 && (
              <>
                <dt>Probe areas</dt>
                <dd>{brief.probe_areas?.join("; ")}</dd>
              </>
            )}
          </dl>
          <ol aria-label="Brief questions">
            {questions.map((q) => (
              <li key={q.id}>
                {q.text} <span className="muted">({(q.competencies ?? []).map(sentence).join(", ")})</span>
              </li>
            ))}
          </ol>
        </div>
      ) : (
        <p className="muted">No brief to show: the user has not given consent, or the brief was not built.</p>
      )}
      {rubric ? (
        <details className="panel">
          <summary>
            Rubric <code>{rubric.ref}</code>
            {rubric.scored ? " (used for this scorecard)" : " (current; not scored yet)"}
          </summary>
          {rubric.text ? <pre className="json-view">{rubric.text}</pre> : <p>The prompt file is no longer in the repo.</p>}
        </details>
      ) : (
        <p className="muted">No rubric recorded.</p>
      )}
    </section>
  );
}
