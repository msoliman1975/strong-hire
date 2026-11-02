/**
 * RMAP-5: the resume a role used was deleted. Deleting is allowed (R1); the role keeps its takes
 * and report and asks for another resume here. "Use this resume" does what RC-6's "Use this one"
 * does, with the existing endpoints and no comparison:
 *
 * 1. the role's analysis with the chosen resume (a ready one is reused, else it runs: GA-4 limits);
 * 2. the role's interviews again on that resume, same types (and Custom setup);
 * 3. the old interviews archived, with their takes (RH-1).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { gapApi } from "../../api/gap";
import { rolesApi } from "../../api/roles";
import type { InterviewWithReadiness, ResumeOut } from "../../api/types";
import { ErrorNotice } from "../../components/ui";
import { START } from "../start/paths";

export async function moveRoleToResume(
  jobId: string,
  resumeId: string,
  stale: readonly InterviewWithReadiness[],
): Promise<void> {
  await gapApi.start(jobId, { resume_id: resumeId, reuse_ready: true });
  const plain = stale.filter((i) => i.interview.interview_type !== "custom");
  if (plain.length > 0) {
    await rolesApi.addInterviews(jobId, {
      resume_id: resumeId,
      interview_types: plain.map((i) => i.interview.interview_type),
    });
  }
  for (const c of stale.filter((i) => i.interview.interview_type === "custom")) {
    await rolesApi.addInterviews(jobId, {
      resume_id: resumeId,
      interview_types: ["custom"],
      custom: c.interview.custom,
    });
  }
  for (const i of stale) await rolesApi.archiveInterview(i.interview.id);
}

export function PickResume({
  jobId,
  interviews,
  resumes,
}: {
  jobId: string;
  /** The role's live interviews; the ones on a deleted resume move. */
  interviews: readonly InterviewWithReadiness[];
  resumes: readonly ResumeOut[];
}) {
  const live = resumes.filter((r) => !r.deleted);
  const fallback = live.find((r) => r.is_main) ?? live[0];
  const [picked, setPicked] = useState(fallback?.id ?? "");
  const client = useQueryClient();
  const liveIds = new Set(live.map((r) => r.id));
  const stale = interviews.filter((i) => !liveIds.has(i.interview.resume_id));
  const move = useMutation({
    mutationFn: () => moveRoleToResume(jobId, picked || fallback?.id || "", stale),
    // The role, its interviews, rehearsals, the plan and Home all show the role's resume.
    onSettled: () => void client.invalidateQueries(),
  });
  return (
    <section className="sx-card" aria-labelledby="pick-resume-heading" data-testid="pick-resume">
      <div className="sx-eyebrow warn">Resume deleted</div>
      <h2 id="pick-resume-heading">Pick a resume for this role</h2>
      <p className="sx-small sx-muted">
        The resume this role used was deleted. Your past takes and the role's report stay. Pick another resume and Strova
        measures it against the posting; your interviews move to it.
      </p>
      {live.length === 0 ? (
        <div className="sx-row">
          <Link className="sx-btn sm" to={START}>
            Add a resume
          </Link>
        </div>
      ) : (
        <div className="sx-row">
          <label htmlFor="pick-resume" className="visually-hidden">
            Resume for this role
          </label>
          <select id="pick-resume" value={picked} onChange={(e) => setPicked(e.target.value)} style={{ width: "auto", maxWidth: "100%" }}>
            {live.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name ?? "Resume"}
                {r.is_main ? " (default)" : ""}
              </option>
            ))}
          </select>
          <button type="button" className="sx-btn sm" disabled={move.isPending} onClick={() => move.mutate()}>
            {move.isPending ? "Moving the role…" : "Use this resume"}
          </button>
        </div>
      )}
      {move.isError && <ErrorNotice error={move.error} />}
    </section>
  );
}
