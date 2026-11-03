/**
 * TG-1, RSD-4 (mockup "Target roles (shared card shell)"): one SummaryCard per target role, with
 * its date chip, three tiles (match, interviews, days left), its resume, and one readiness bar per
 * interview. The card is not a link (D-2): Show details is the way in.
 */
import { Link } from "react-router";

import { useJobs, useResumes } from "../../api/hooks";
import { useRoles } from "../../api/roles";
import { ErrorNotice, Loading } from "../../components/ui";
import { AddCard, SummaryCard, type StatTileProps } from "../../components/ux/SummaryCard";
import "../../components/ux/ux.css";
import { addRolePath, dateChip, ReadinessRow, resumeGone, resumeLabel, rolePath, roleTitle } from "./shared";

/** RSD-4: match, interviews and days left; "—" when a number is unknown. */
export function roleStats(
  match: number | null | undefined,
  interviews: number,
  daysLeft: number | null | undefined,
): readonly [StatTileProps, StatTileProps, StatTileProps] {
  const soon = daysLeft !== null && daysLeft !== undefined && daysLeft >= 0;
  return [
    { value: match ?? "—", label: "match" },
    { value: interviews, label: interviews === 1 ? "interview" : "interviews" },
    soon ? { value: daysLeft, label: daysLeft === 1 ? "day left" : "days left", tone: "teal" } : { value: "—", label: "days left" },
  ];
}

export function RolesPage() {
  const roles = useRoles();
  const jobs = useJobs();
  const resumes = useResumes();
  return (
    <div className="sx-page">
      <div className="sx-between">
        <h1>Target roles</h1>
        <Link className="sx-btn" to={addRolePath}>
          Add a target role
        </Link>
      </div>
      <p className="sx-muted">
        Each role is a real job posting. Strova suggests the interviews to rehearse for it, measured against your resume.
      </p>
      {roles.isPending && <Loading label="Loading your target roles" />}
      {roles.isError && <ErrorNotice error={roles.error} />}
      {roles.data?.length === 0 && (
        <div className="sx-card dashed">
          <h2>No target role yet</h2>
          <p className="sx-small sx-muted">Add a job posting and Strova suggests the interviews to rehearse.</p>
        </div>
      )}
      {roles.data && roles.data.length > 0 && (
        <div className="sx-grid2 stretch">
          {roles.data.map(({ role, interviews }) => {
            const job = jobs.data?.find((j) => j.job_target.id === role.id);
            const chip = dateChip(role, job?.job_target.stage);
            const resumeId = interviews[0]?.interview.resume_id;
            const title = roleTitle(role);
            return (
              <SummaryCard
                key={role.id}
                title={title}
                chip={<span className={`sx-chip${chip.teal ? " t" : ""}`}>{chip.text}</span>}
                stats={roleStats(job?.match_score, interviews.length, role.days_left)}
                meta={resumeLabel(resumes.data, resumeId)}
                primary={
                  <Link className="sx-btn sm" to={rolePath(role.id)} aria-label={`Show details: ${title}`}>
                    Show details
                  </Link>
                }
              >
                {resumeGone(resumes.data, resumeId) && (
                  <span className="sx-chip warn" style={{ alignSelf: "flex-start" }}>
                    Pick a resume for this role
                  </span>
                )}
                <div className="sx-stack" style={{ gap: 8 }}>
                  {interviews.length === 0 && <span className="sx-small sx-muted">No interviews kept yet.</span>}
                  {interviews.map((i) => (
                    <ReadinessRow key={i.interview.id} item={i} />
                  ))}
                </div>
              </SummaryCard>
            );
          })}
          <AddCard to={addRolePath} title="Add a target role" hint="Paste a job posting and Strova suggests the interviews." />
        </div>
      )}
    </div>
  );
}
