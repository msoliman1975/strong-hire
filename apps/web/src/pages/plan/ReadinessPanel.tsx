/**
 * RD-1: practice readiness per tested skill on the plan page, from Realistic rehearsals only.
 * The count of skills at the bar sits next to the per-skill rows, never alone. RD-3: the
 * practice-estimate notice is always shown.
 */
import { useState, type CSSProperties } from "react";

import { Bar, ErrorNotice, Loading } from "../../components/ui";
import { competencyLabel } from "../../labels";
import {
  atBar,
  BAR_SCORE,
  MIN_SESSIONS,
  READINESS_NOTICE_SHORT,
  scored,
  useReadiness,
  type SkillReadiness,
} from "./ReadinessApi";
import { ReadinessNotice } from "./ReadinessNotice";
import "./Readiness.css";

function SkillRow({ skill }: { skill: SkillReadiness }) {
  const name = competencyLabel(skill.competency);
  if (skill.score === null) {
    return (
      <li className="readiness-skill" data-testid="readiness-skill">
        <span>{name}</span>
        <span className="muted small">
          Not enough data yet: {skill.sessions_counted} of {MIN_SESSIONS} Realistic rehearsals
        </span>
      </li>
    );
  }
  return (
    <li className="readiness-skill" data-testid="readiness-skill">
      <span>{name}</span>
      <span className="readiness-skill__score">
        <Bar value={skill.score} label={`${name}: ${skill.score} of 100`} />
        <span className="small">
          {skill.score}
          {skill.score >= BAR_SCORE ? " · at the bar" : ""}
        </span>
      </span>
    </li>
  );
}

/**
 * RD-1 in the plan's header (canvas board B1 Plan): a ring with the share of tested skills at the
 * bar, and the count in text. Shown once a skill is scored. RD-3: with the short notice.
 */
export function ReadinessRing({ jobId, resumeId }: { jobId: string; resumeId: string }) {
  const readiness = useReadiness(jobId, resumeId);
  if (!readiness.data || scored(readiness.data) === 0) return null;
  const total = readiness.data.skills.length;
  const done = atBar(readiness.data);
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="readiness-ring" data-testid="readiness-ring">
      <span className="readiness-ring__dial" style={{ "--pct": `${pct}%` } as CSSProperties} aria-hidden="true">
        {done}/{total}
      </span>
      <span>
        <b>Practice readiness</b>
        <span className="small muted">
          {done} of {total} skills at the bar. {READINESS_NOTICE_SHORT}
        </span>
      </span>
    </div>
  );
}

export function ReadinessPanel({ jobId, resumeId }: { jobId: string; resumeId: string }) {
  const readiness = useReadiness(jobId, resumeId);
  const [open, setOpen] = useState(false);
  return (
    <section className="card" aria-labelledby="plan-readiness-heading" data-testid="readiness-panel">
      <h2 id="plan-readiness-heading">Practice readiness</h2>
      <ReadinessNotice />
      {readiness.isPending ? (
        <Loading label="Loading your practice readiness" />
      ) : readiness.isError ? (
        <ErrorNotice error={readiness.error} />
      ) : (
        <>
          <p className="muted">
            {scored(readiness.data) === 0
              ? `Run ${MIN_SESSIONS} Realistic rehearsals to see how ready your practice shows you to be.`
              : `${atBar(readiness.data)} of ${readiness.data.skills.length} skills at the bar of 3 of 4.`}
          </p>
          {/* Before any skill is scored every row says the same thing, so the rows fold away. */}
          {scored(readiness.data) > 0 || open ? (
            <ul className="plain-list readiness-skills">
              {readiness.data.skills.map((s) => (
                <SkillRow key={s.competency} skill={s} />
              ))}
            </ul>
          ) : (
            <button className="btn btn--quiet" type="button" onClick={() => setOpen(true)}>
              Show each skill ({readiness.data.skills.length})
            </button>
          )}
        </>
      )}
    </section>
  );
}
