/** RD-3: the practice-estimate notice, on every screen that shows readiness. */
import { READINESS_NOTICE, READINESS_NOTICE_SHORT } from "./ReadinessApi";

export function ReadinessNotice({ short = false }: { short?: boolean }) {
  return (
    <p className="readiness-notice small muted" data-testid="readiness-notice">
      {short ? READINESS_NOTICE_SHORT : READINESS_NOTICE}
    </p>
  );
}
