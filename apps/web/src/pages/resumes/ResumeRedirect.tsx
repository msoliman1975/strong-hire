/**
 * RSD-6, D-1: the resume detail page is retired. `/resumes/:id` sends to the check page and keeps
 * its query string, so old links (Home, emails, the plan's `action_target`) keep working.
 */
import { Navigate, useLocation, useParams } from "react-router";

import { resumeCheckPath } from "../../paths";

export function ResumeRedirect() {
  const { resumeId = "" } = useParams();
  const { search, hash } = useLocation();
  return <Navigate replace to={{ pathname: resumeCheckPath(resumeId), search, hash }} />;
}
