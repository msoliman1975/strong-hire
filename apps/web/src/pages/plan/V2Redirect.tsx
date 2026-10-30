/**
 * U07: with `v2_enabled` on, the gap analysis, rehearsals (PR-3), session setup and the retired
 * v2 plan page (`/interviews/:jobId/:resumeId`) open the target role page instead (TG-4), where
 * the role's interviews start their takes. With the flag off, the v1 page shows as before. An
 * earlier report (`/jobs/:id/gap?report=`) still opens on the old page.
 */
import type { ReactNode } from "react";
import { Navigate, useParams, useSearchParams } from "react-router";

import { useFeature } from "../../theme/features";
import { rolePath } from "../roles/shared";

export function V2Redirect({ children }: { children: ReactNode }) {
  const v2 = useFeature("v2_enabled");
  if (!v2) return <>{children}</>;
  return <ToPlan>{children}</ToPlan>;
}

function ToPlan({ children }: { children: ReactNode }) {
  const { jobId = "" } = useParams();
  const [params] = useSearchParams();
  if (params.get("report")) return <>{children}</>;
  return <Navigate to={rolePath(jobId)} replace />;
}

/** The retired v2 plan page: its old links open the role page. */
export function RetiredPlanRedirect() {
  const { jobId = "" } = useParams();
  return <Navigate to={rolePath(jobId)} replace />;
}
