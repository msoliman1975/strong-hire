import { Link } from "react-router";

import type { CustomRecommendation } from "../api/types";
import { interviewTypeLabel } from "../labels";
import { practiceTitle, setupPath, type SetupState } from "./repeat";

/**
 * CU-10: a recommended Custom session, "Practice conflict handling and Kubernetes". The button
 * opens the Custom setup prefilled with its categories, chips and length. With `headingId` the
 * title is the card's heading.
 */
export function CustomNext({ jobId, rec, headingId }: { jobId: string; rec: CustomRecommendation; headingId?: string }) {
  const state: SetupState = { recommended: rec };
  const title = practiceTitle(rec);
  return (
    <div data-testid="custom-next">
      {headingId ? (
        <h2 id={headingId}>{title}</h2>
      ) : (
        <p>
          <strong>{title}</strong>
        </p>
      )}
      <p className="muted small">
        {interviewTypeLabel.custom} interview, {rec.custom.categories.map((c) => interviewTypeLabel[c.category]).join(", ")},{" "}
        {rec.duration_min} minutes. {rec.reason}
      </p>
      <Link className="btn" to={setupPath(jobId)} state={state}>
        Set up this Custom interview
      </Link>
    </div>
  );
}
