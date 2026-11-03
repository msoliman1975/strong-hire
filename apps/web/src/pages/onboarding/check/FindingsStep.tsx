/**
 * RSD-10: step 2, "Strova's findings". One finding at a time, high first, with the fix in place in
 * a "Strova recommends" box: the date fields of the roles involved, the achievement, the summary,
 * or "Add {skills}". Every accept reason stays (IN-12), and so does the gap practice link. The
 * checks are the client-side rules of `resumeChecks.ts` (D-7); `ResumeCheckV2` owns the draft.
 */
import { useId, type ReactNode } from "react";
import { Link } from "react-router";

import { ErrorNotice } from "../../../components/ui";
import type { AcceptedIssues } from "../acceptedIssues";
import type { ResumeIssue } from "../resumeChecks";
import type { CvRole } from "./draft";

/** High first, then the order the checks found them in. */
export function orderFindings(open: readonly ResumeIssue[]): ResumeIssue[] {
  return [...open.filter((i) => i.severity === "high"), ...open.filter((i) => i.severity !== "high")];
}

export const gapPracticePath = (gap: { from: string; to: string }, jobId: string) => {
  const ask = `Help me answer "tell me about this gap" for ${gap.from} to ${gap.to}.`;
  return `/coach/new?ask=${encodeURIComponent(ask)}${jobId ? `&job=${encodeURIComponent(jobId)}` : ""}`;
};

/** The label of the reason a finding was accepted with, if it is one of its reasons. */
export const acceptedReason = (issue: ResumeIssue, code: string | undefined) =>
  code ? (issue.reasons?.find((r) => r.code === code)?.label ?? null) : null;

/** What Strova checks (D-7). A drawer in RS05; the content lives here. */
export function WhatStrovaChecks() {
  return (
    <ul className="cvc-checks-list">
      <li>
        <b>Dates:</b> gaps over 3 months, overlapping roles, end before start, future dates, years only, missing dates,
        current role not marked. Left old dates off on purpose? Accept it and say why.
      </li>
      <li>
        <b>Detail:</b> roles with fewer than 2 achievements, achievements with no result (a number, a measure that moved,
        or the scale), "we" with no "I", a very short or missing summary.
      </li>
      <li>
        <b>Fit for level:</b> a Senior target with no scope signals (team size, budget, cross-team work).
      </li>
      <li>
        <b>Consistency:</b> skills used in roles but missing from Skills, the same company listed twice.
      </li>
      <li>
        <b>Against a job:</b> when you check it for an interview, the job's must-have skills that your resume never shows.
      </li>
    </ul>
  );
}

const roleName = (r: CvRole | undefined) => (r ? r.company.trim() || r.title.trim() || "this role" : "this role");

/** The skills a skills finding names, from its detail ("Kafka, Terraform"). */
export const findingSkills = (issue: ResumeIssue) =>
  issue.target.section === "skills" ? issue.detail.split(",").map((s) => s.trim()).filter(Boolean) : [];

/** Which date fields fix a dates finding: for a gap, the older role's end and the newer one's start. */
export function dateFields(issue: ResumeIssue): { role: number; field: "start" | "end" }[] {
  if (issue.group !== "dates" || issue.target.section !== "role") return [];
  const target = issue.target.role;
  if (issue.gap) {
    const older = issue.roles.find((r) => r !== target);
    return [...(older === undefined ? [] : [{ role: older, field: "end" as const }]), { role: target, field: "start" }];
  }
  const roles = issue.roles.length ? issue.roles : [target];
  return roles.flatMap((role) => [
    { role, field: "start" as const },
    { role, field: "end" as const },
  ]);
}

/** The achievement a detail finding points at: its index, or the next empty line to write. */
export function achievementSlot(issue: ResumeIssue, role: CvRole | undefined): number | null {
  if (issue.target.section !== "role" || !role) return null;
  if (issue.target.field === "achievement") return issue.target.item ?? 0;
  if (issue.target.field === "achievements") {
    const empty = role.achievements.findIndex((a) => !a.trim());
    return empty >= 0 ? empty : role.achievements.length;
  }
  return null;
}

export interface FindingsStepProps {
  /** Open findings, in order (`orderFindings`). */
  findings: ResumeIssue[];
  current: number;
  onSelect: (index: number) => void;
  /** The roles as the user sees them (open editors included). */
  roles: CvRole[];
  /** The saved roles, so the achievement a fix writes to stays put while it is typed. */
  savedRoles: CvRole[];
  summary: string;
  jobId: string;
  accepted: AcceptedIssues;
  saving: boolean;
  /** Field errors of a role, by key. */
  errorFor: (role: CvRole, field: "start" | "end") => string | undefined;
  onRoleField: (role: number, field: "start" | "end" | "title", value: string) => void;
  onAchievement: (role: number, item: number, text: string) => void;
  onSummary: (text: string) => void;
  /** Saves the fix in place, then the next finding shows. */
  onSave: () => void;
  onAddSkills: (skills: string[]) => void;
  /** A finding with no fix in place: open its field on step 1. */
  onFixElsewhere: (issue: ResumeIssue) => void;
  onOpenJourney: () => void;
}

export function FindingsStep(props: FindingsStepProps) {
  const { findings, current } = props;
  const headingId = useId();
  const finding = findings[Math.min(current, findings.length - 1)];
  const index = finding ? findings.indexOf(finding) : -1;

  return (
    <section className="cvc-step-view cvc-findings" aria-labelledby="cvc-findings-h" data-testid="findings-step">
      <h2 id="cvc-findings-h" className="visually-hidden">
        Strova's findings
      </h2>
      {props.accepted.error != null && <ErrorNotice error={props.accepted.error} title="We could not save that." />}
      {!finding ? (
        <div className="cvc-card cvc-clear">
          <p>Nothing to fix. Your resume reads well.</p>
          <button type="button" className="cvc-link" onClick={props.onOpenJourney}>
            See your career journey
          </button>
        </div>
      ) : (
        <article className="cvc-card cvc-finding" aria-labelledby={headingId} data-severity={finding.severity} data-group={finding.group}>
          <div className="cvc-finding__top">
            <span className="cvc-label" data-testid="finding-position">
              Finding {index + 1} of {findings.length} · {finding.severity}
            </span>
            <span className="cvc-finding__nav">
              <button
                type="button"
                className="sx-btn quiet sm"
                aria-label="Previous finding"
                disabled={index <= 0}
                onClick={() => props.onSelect(index - 1)}
              >
                ‹
              </button>
              <button
                type="button"
                className="sx-btn quiet sm"
                aria-label="Next finding"
                disabled={index >= findings.length - 1}
                onClick={() => props.onSelect(index + 1)}
              >
                ›
              </button>
            </span>
          </div>
          <h3 id={headingId} className="cvc-finding__title">
            {finding.title}
          </h3>
          <p className="cvc-finding__detail">
            {finding.detail}
            {finding.detail ? ". " : ""}
            {finding.why}
          </p>
          <Recommends {...props} finding={finding} />
          <div className="row cvc-finding__actions">
            <button type="button" className="btn btn--secondary btn--small" onClick={() => props.accepted.accept(finding.key)}>
              {finding.acceptLabel}
            </button>
            {finding.reasons?.map((r) => (
              <button
                key={r.code}
                type="button"
                className="btn btn--secondary btn--small"
                onClick={() => props.accepted.accept(finding.key, r.code)}
                aria-label={`Accept: ${r.label}`}
              >
                {r.label}
              </button>
            ))}
          </div>
          {finding.gap && (
            <Link to={gapPracticePath(finding.gap, props.jobId)} className="cvc-practice">
              Practice "tell me about this gap" with Strova
            </Link>
          )}
        </article>
      )}

      {findings.length > 1 && (
        <div className="cvc-next-findings">
          <p className="cvc-label">Next findings</p>
          <ul className="cvc-finding-rows" aria-label="Next findings">
            {findings.map((f, i) =>
              i === index ? null : (
                <li key={f.key}>
                  <button type="button" className="cvc-card cvc-finding-row" onClick={() => props.onSelect(i)}>
                    <span>
                      <b>{f.title}</b>
                      {f.detail && <span className="muted"> · {f.detail}</span>}
                    </span>
                    {f.severity === "high" && <span className="cvc-chip cvc-chip--bad">high</span>}
                  </button>
                </li>
              ),
            )}
          </ul>
        </div>
      )}

    </section>
  );
}

/** RSD-14: the findings the user accepted, each with its reason and Undo (IN-12). */
export function AcceptedList({ findings, accepted }: { findings: ResumeIssue[]; accepted: AcceptedIssues }) {
  if (findings.length === 0) return <p className="muted">Nothing accepted yet.</p>;
  return (
    <ul className="cvc-drawer__rows" aria-label="Findings you accepted">
      {findings.map((issue) => {
        const why = acceptedReason(issue, accepted.reasons.get(issue.key));
        return (
          <li key={issue.key} className="cvc-drawer__row cvc-accepted">
            <span>
              ✓ Accepted: {issue.title}
              {why && <span className="cvc-accepted__why"> · {why}</span>}
            </span>
            <button
              type="button"
              className="cvc-link"
              onClick={() => accepted.undo(issue.key)}
              aria-label={`Undo accepting ${issue.title}`}
            >
              Undo
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** The fix, in place. */
function Recommends(props: FindingsStepProps & { finding: ResumeIssue }) {
  const { finding, roles } = props;
  const dates = dateFields(finding);
  const skills = findingSkills(finding);
  const target = finding.target;
  const role = target.section === "role" ? roles[target.role] : undefined;
  const slot = achievementSlot(finding, target.section === "role" ? props.savedRoles[target.role] : undefined);
  const id = `fix-${finding.key.replace(/[^a-z0-9]+/gi, "-")}`;

  let body: ReactNode;
  let save: string | null = null;
  if (dates.length > 0) {
    save = "Save dates";
    body = (
      <div className="cvc-fix-fields">
        {dates.map(({ role: r, field }) => {
          const fieldId = `${id}-${r}-${field}`;
          const error = roles[r] ? props.errorFor(roles[r], field) : undefined;
          return (
            <div className="field" key={fieldId}>
              <label htmlFor={fieldId}>
                {roleName(roles[r])} {field === "start" ? "started" : "ended"}
              </label>
              <input
                id={fieldId}
                type="text"
                value={roles[r]?.[field] ?? ""}
                placeholder={field === "end" ? "Empty if current" : "YYYY-MM"}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? `${fieldId}-error` : undefined}
                onChange={(e) => props.onRoleField(r, field, e.target.value)}
              />
              {error && (
                <p className="field-error" id={`${fieldId}-error`}>
                  {error}
                </p>
              )}
            </div>
          );
        })}
      </div>
    );
  } else if (slot !== null && target.section === "role") {
    save = "Save achievement";
    const fieldId = `${id}-achievement`;
    body = (
      <div className="field">
        <label htmlFor={fieldId}>
          {target.field === "achievements" ? `A new achievement at ${roleName(role)}` : `Achievement at ${roleName(role)}`}
        </label>
        <textarea
          id={fieldId}
          rows={3}
          value={role?.achievements[slot] ?? ""}
          onChange={(e) => props.onAchievement(target.role, slot, e.target.value)}
        />
      </div>
    );
  } else if (target.section === "summary") {
    save = "Save summary";
    const fieldId = `${id}-summary`;
    body = (
      <div className="field">
        <label htmlFor={fieldId}>Summary</label>
        <textarea id={fieldId} rows={4} value={props.summary} onChange={(e) => props.onSummary(e.target.value)} />
      </div>
    );
  } else if (skills.length > 0) {
    body = (
      <div className="row">
        <button type="button" className="btn btn--small" disabled={props.saving} onClick={() => props.onAddSkills(skills)}>
          Add {skills.join(", ")}
        </button>
      </div>
    );
  } else {
    body = (
      <div className="row">
        <button type="button" className="btn btn--small" onClick={() => props.onFixElsewhere(finding)}>
          {finding.fixLabel}
        </button>
      </div>
    );
  }

  return (
    <div className="cvc-recommends">
      <span className="cvc-label">Strova recommends</span>
      <p>{finding.fixLabel}.</p>
      {body}
      {save && (
        <div className="row">
          <button type="button" className="btn btn--small" disabled={props.saving} onClick={props.onSave}>
            {save}
          </button>
        </div>
      )}
    </div>
  );
}
