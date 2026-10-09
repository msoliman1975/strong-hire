import { Link } from "react-router";

import { JobLibrary } from "../components/LibrarySection";
import { PageHead } from "../components/ui";
import { newJobPath } from "../paths";

/**
 * LB-2: the saved job descriptions. One with no reports can be deleted; one with reports is
 * archived instead, and "Show archived" lists those again so they can be restored.
 */
export function JobsPage() {
  return (
    <div className="page--narrow">
      <PageHead title="Job descriptions">
        <div className="page-head__row">
          <p>
            The job postings you rehearse for. You can delete one that has no reports. One with reports is archived
            instead, so its reports keep their job.
          </p>
          <Link className="btn" to={newJobPath("library")}>
            Add a job description
          </Link>
        </div>
      </PageHead>
      <JobLibrary
        empty={
          <p className="muted">
            You have no saved job descriptions. <Link to={newJobPath("library")}>Add the first one</Link>.
          </p>
        }
      />
    </div>
  );
}
