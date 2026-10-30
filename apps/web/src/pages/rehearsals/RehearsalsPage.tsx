/**
 * RH-4 (mockup #rehearse): Strova as the interviewer, the recommended next take, then every
 * interview across the target roles with its readiness and Retake or Start.
 */
import { Link } from "react-router";

import { useRehearsals } from "../../api/roles";
import type { RehearsalItem } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { DEFAULT_TAKE_MINUTES, interviewPath, takesMeta, typeName } from "../roles/shared";

const GOAL = 75;

function company(item: RehearsalItem): string {
  return item.role.company_name ?? item.role.name ?? "Role";
}

/** Why this take: the date first, then the gap to the goal. */
function why(item: RehearsalItem): string {
  const parts: string[] = [];
  if (item.role.days_left !== null && item.role.days_left >= 0) parts.push("Closest to your interview date");
  const score = item.readiness.score;
  if (score === null) parts.push("your first Realistic take sets your starting readiness");
  else parts.push(`${GOAL - score} points from your readiness goal`);
  const text = parts.join(", and ");
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
}

export function RehearsalsPage() {
  const data = useRehearsals();
  const next = data.data?.items.find((i) => i.interview.id === data.data?.next_interview_id) ?? null;
  return (
    <div className="sx-page">
      <div className="sx-row">
        <Strova mode="interviewing" size={72} />
        <div>
          <h1>Rehearsals with Strova</h1>
          <p className="sx-muted sx-small">
            Rehearse every interview across your target roles with Strova, who plays the interviewer.
          </p>
        </div>
      </div>
      {data.isPending && <Loading label="Loading your rehearsals" />}
      {data.isError && <ErrorNotice error={data.error} />}
      {next && (
        <section className="sx-hero" aria-label="Recommended next take">
          <span className="sx-eyebrow" style={{ color: "var(--sh-teal-light)" }}>
            Recommended next take
          </span>
          <div className="big">
            {company(next)} · {typeName(next.interview)}, Realistic, {DEFAULT_TAKE_MINUTES} minutes
          </div>
          <div className="sub">{why(next)}</div>
          <div className="sx-row">
            <Link className="sx-btn" to={interviewPath(next.interview.id)}>
              {next.takes_count === 0 ? "Start the first take" : "Start the take"}
            </Link>
          </div>
        </section>
      )}
      {data.data && data.data.items.length === 0 && (
        <div className="sx-card dashed">
          <h2>No interviews yet</h2>
          <p className="sx-small sx-muted">Add a target role and keep the interviews Strova suggests.</p>
          <div className="sx-row">
            <Link className="sx-btn ghost sm" to="/roles/new">
              Add a target role
            </Link>
          </div>
        </div>
      )}
      {data.data && data.data.items.length > 0 && (
        <div className="sx-card">
          {data.data.items.map((item) => {
            const score = item.readiness.score;
            return (
              <Link key={item.interview.id} className="sx-list-row" to={interviewPath(item.interview.id)}>
                <div className="sx-stack" style={{ gap: 4, flex: "1 1 300px" }}>
                  <strong>
                    {company(item)} · {typeName(item.interview)}
                  </strong>
                  <span className="sx-small sx-muted">{takesMeta(item)}</span>
                </div>
                <div style={{ flex: "0 1 220px", minWidth: 140 }}>
                  <div className="sx-between sx-small">
                    <span className="sx-muted">Readiness</span>
                    <span className="sx-mono">{score ?? "–"}</span>
                  </div>
                  <div className="sx-bar">
                    <span style={{ width: `${score ?? 0}%` }} />
                  </div>
                </div>
                <span className={`sx-btn sm${score === null ? " ghost" : ""}`}>{item.takes_count === 0 ? "Start" : "Retake"}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
