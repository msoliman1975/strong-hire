import { Link } from "react-router";

import type { Debrief } from "../../api/types";
import { CustomNext } from "../../custom/CustomNext";
import { difficultyLabel, interviewTypeLabel } from "../../labels";
import { setupLink } from "../GapAnalysisPage";

/** PR-2 on the v2 debrief: the next session in the plan, or a Custom one (CU-10). */
export function NextInPlan({ debrief }: { debrief: Debrief }) {
  const jobId = debrief.session.job_target_id;
  const next = debrief.next_session;
  return (
    <section className="card card--prep-soft debrief-next" aria-labelledby="debrief-next-heading">
      <h2 id="debrief-next-heading">Next in your plan</h2>
      {debrief.next_custom_session ? (
        <CustomNext jobId={jobId} rec={debrief.next_custom_session} />
      ) : next ? (
        <>
          <p>
            <strong>
              {interviewTypeLabel[next.interview_type]}, {difficultyLabel[next.difficulty]}
            </strong>
            {next.focus_topics.length > 0 && `: ${next.focus_topics.join(", ")}`}. {next.reason}
          </p>
          <Link className="btn btn--ink" to={setupLink(jobId, next)}>
            Start this rehearsal
          </Link>
        </>
      ) : (
        <Link className="btn btn--ink" to={setupLink(jobId)}>
          Set up another session
        </Link>
      )}
    </section>
  );
}
