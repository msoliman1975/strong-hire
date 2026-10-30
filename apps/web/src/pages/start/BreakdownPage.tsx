/**
 * ON-4 (mockup #resume-check): the breakdown and the issues on one screen, with the v2 check's
 * editing, fix and accept actions (ResumeCheckV2), then Back and Continue.
 */
import { Link, useParams } from "react-router";

import { useResume } from "../../api/hooks";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { ResumeCheckV2 } from "../onboarding/ResumeCheckV2";
import { PLAN_STYLE, readyPath } from "./paths";

export function BreakdownPage() {
  const { resumeId = "" } = useParams();
  const record = useResume(resumeId);
  if (record.isError) return <ErrorNotice error={record.error} />;
  if (!record.data?.resume) return <Loading label="Loading your resume" />;
  return (
    <div className="sx-solo sx-solo--wide">
      <Link className="sx-small" to={readyPath(resumeId)}>
        Back to what your resume shows
      </Link>
      <ResumeCheckV2
        key={resumeId}
        jobId=""
        resumeId={resumeId}
        name={record.data.name}
        original={record.data.resume}
        accepted={record.data.accepted_issues}
        fresh={false}
        confirmedAt={record.data.confirmed_at ?? null}
        uploadedAt={record.data.uploaded_at}
        onboarding={{ continueTo: PLAN_STYLE, backTo: readyPath(resumeId) }}
      />
    </div>
  );
}
