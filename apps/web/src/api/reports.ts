/**
 * The Reports page (R1): every gap report and interview debrief of the signed-in user, newest
 * first. Filter by job and by type.
 */
import { apiClient, unwrap } from "./client";
import type { ReportItem, ReportType } from "./types";

export interface ReportFilter {
  jobTargetId?: string | null;
  type?: ReportType | null;
}

export const reportsApi = {
  list: async (filter: ReportFilter = {}) =>
    unwrap(
      await apiClient.GET("/reports", {
        params: {
          query: {
            job_target_id: filter.jobTargetId ?? undefined,
            type: filter.type ?? undefined,
          },
        },
      }),
    ) as ReportItem[],
};

/** Where a report row opens: the existing gap analysis or debrief page. */
export function reportPath(report: ReportItem): string {
  return report.type === "gap_report"
    ? `/jobs/${report.job_target_id}/gap?report=${encodeURIComponent(report.id)}`
    : `/sessions/${report.id}/debrief`;
}
