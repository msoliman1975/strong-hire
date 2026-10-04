import { Link } from "react-router";

import type { Usage } from "../api/planned";

/** BL-1: minutes used of the monthly cap. The numbers come from the API as they are. */
export function UsageMeter({ usage }: { usage: Usage }) {
  if (usage.plan === "free") {
    const text = usage.free_interview_available
      ? "Free plan: 1 free interview left"
      : "Free plan: free interview used";
    return (
      <Link className="usage" to="/upgrade" data-testid="usage-meter">
        <span>{text}</span>
        <span className="muted">Upgrade for more interviews</span>
      </Link>
    );
  }
  const cap = Math.max(usage.minutes_cap, 0);
  const pct = cap > 0 ? Math.min(100, (usage.minutes_used / cap) * 100) : 100;
  return (
    <div className="usage" data-testid="usage-meter">
      <span id="usage-label">
        {usage.minutes_used} of {cap} minutes used
      </span>
      <div
        className="usage__track"
        role="meter"
        aria-labelledby="usage-label"
        aria-valuemin={0}
        aria-valuemax={cap}
        aria-valuenow={Math.min(usage.minutes_used, cap)}
      >
        <div className="usage__fill" data-level={pct >= 90 ? "high" : undefined} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
