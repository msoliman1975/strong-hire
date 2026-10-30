/**
 * TG-1 (mockup #roles): one card per target role with its date chip, resume and match, and one
 * readiness bar per interview.
 */
import { Link } from "react-router";

import { useJobs, useResumes } from "../../api/hooks";
import { useRoles } from "../../api/roles";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { addRolePath, dateChip, ReadinessRow, resumeLabel, rolePath, roleTitle } from "./shared";

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
      <div className="sx-grid2">
        {roles.data?.map(({ role, interviews }) => {
          const job = jobs.data?.find((j) => j.job_target.id === role.id);
          const chip = dateChip(role, job?.job_target.stage);
          const match = job?.match_score;
          return (
            <Link key={role.id} className="sx-card" to={rolePath(role.id)} style={{ textDecoration: "none", color: "inherit" }}>
              <div className="sx-between">
                <h2>{roleTitle(role)}</h2>
                <span className={`sx-chip${chip.teal ? " t" : ""}`}>{chip.text}</span>
              </div>
              <span className="sx-small sx-muted">
                {resumeLabel(resumes.data, interviews[0]?.interview.resume_id)}
                {match !== null && match !== undefined ? ` · match ${match}` : ""}
              </span>
              <div className="sx-stack" style={{ gap: 8 }}>
                {interviews.length === 0 && <span className="sx-small sx-muted">No interviews kept yet.</span>}
                {interviews.map((i) => (
                  <ReadinessRow key={i.interview.id} item={i} />
                ))}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
