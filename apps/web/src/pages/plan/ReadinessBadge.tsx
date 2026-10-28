/**
 * RD-1 on the Home interview card: how many tested skills are at the bar, for the job's latest
 * job and CV pair. RD-3: with the short practice-estimate notice.
 */
import { StatusBadge } from "../../components/ui";
import { atBar, MIN_SESSIONS, scored, useJobReadiness } from "./ReadinessApi";
import { ReadinessNotice } from "./ReadinessNotice";
import "./Readiness.css";

export function ReadinessBadge({ jobId }: { jobId: string }) {
  const readiness = useJobReadiness(jobId);
  if (!readiness.data) return null;
  const r = readiness.data;
  const any = scored(r) > 0;
  return (
    <div className="readiness-badge" data-testid="readiness-badge">
      <StatusBadge tone={any ? "prep" : "neutral"}>
        {any
          ? `Practice readiness: ${atBar(r)} of ${r.skills.length} skills at the bar`
          : `Readiness after ${MIN_SESSIONS} Realistic rehearsals`}
      </StatusBadge>
      <ReadinessNotice short />
    </div>
  );
}
