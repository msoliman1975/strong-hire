/**
 * PP-1: with `v2_enabled` on, the gap analysis, rehearsals (PR-3) and session setup routes open
 * the plan page of their job and CV pair instead. With the flag off, the v1 page shows as before.
 *
 * The CV comes from the route (rehearsals), `?resume=` (setup), or the job's latest gap
 * analysis. Query and router state (CU-9, CU-10 prefills) go along to the plan page's setup.
 * An earlier report (`/jobs/:id/gap?report=`) still opens on the old page.
 */
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate, useLocation, useParams, useSearchParams } from "react-router";

import { gapApi } from "../../api/gap";
import { keys } from "../../api/hooks";
import { Loading } from "../../components/ui";
import { useFeature } from "../../theme/features";
import { planPath } from "./paths";

export function V2Redirect({ children }: { children: ReactNode }) {
  const v2 = useFeature("v2_enabled");
  if (!v2) return <>{children}</>;
  return <ToPlan>{children}</ToPlan>;
}

function ToPlan({ children }: { children: ReactNode }) {
  const { jobId = "", resumeId: routeResume } = useParams();
  const [params] = useSearchParams();
  const location = useLocation();
  const known = routeResume ?? params.get("resume");
  const report = params.get("report");
  const latest = useQuery({
    queryKey: keys.gap(jobId),
    queryFn: () => gapApi.get(jobId),
    retry: false,
    enabled: !known && !report,
  });
  if (report) return <>{children}</>;

  const resumeId = known ?? latest.data?.resume_id ?? null;
  if (!resumeId && latest.isLoading) return <Loading />;
  // No CV for this job yet: the v1 page knows how to get one.
  if (!resumeId) return <>{children}</>;

  const query = new URLSearchParams(params);
  query.delete("resume");
  const search = query.toString();
  return (
    <Navigate to={`${planPath(jobId, resumeId)}${search ? `?${search}` : ""}`} state={location.state as unknown} replace />
  );
}
