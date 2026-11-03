import { useSearchParams } from "react-router";

import { useJobs, useReports } from "../api/hooks";
import type { ReportType } from "../api/types";
import { ReportList, reportTypeLabel } from "../components/ReportList";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import "../components/ux/ux.css";
import { useFeature } from "../theme/features";
import "./home/StoryLibrary.css";
import { StoriesToWorkOn } from "./progress/StoriesToWorkOn";
import "./progress/progress.css";
import { ReportsByRole } from "./reports/ReportsByRole";

const TYPES = Object.keys(reportTypeLabel) as ReportType[];

/**
 * R1: every gap report and interview debrief, newest first, filtered by job and by type. With
 * `v2_enabled` on (NV-4) it is the last rail item: the reports grouped by target role on the
 * shared card shell, then the stories that need work.
 */
export function ReportsPage() {
  const v2 = useFeature("v2_enabled");
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job") || null;
  const rawType = params.get("type");
  const type = TYPES.includes(rawType as ReportType) ? (rawType as ReportType) : null;
  const reports = useReports({ jobTargetId: jobId, type });
  const jobs = useJobs();

  const setFilter = (name: "job" | "type", value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };

  // A deleted job is not in the job list, but its reports are. Keep the filter usable.
  const filterJobMissing = jobId !== null && jobs.data !== undefined && !jobs.data.some((j) => j.job_target.id === jobId);

  const filters = (
    <div className={v2 ? "sx-row" : "row section"} role="group" aria-label="Filters">
      <div className={v2 ? "sx-field" : "field"}>
        <label htmlFor="report-job">{v2 ? "Target role" : "Job"}</label>
        <select id="report-job" value={jobId ?? ""} onChange={(e) => setFilter("job", e.target.value)}>
          <option value="">{v2 ? "All target roles" : "All jobs"}</option>
          {(jobs.data ?? []).map((j) => (
            <option key={j.job_target.id} value={j.job_target.id}>
              {j.job_target.name ?? (v2 ? "Target role" : "Job")}
            </option>
          ))}
          {filterJobMissing && <option value={jobId}>{v2 ? "Deleted target role" : "Deleted job"}</option>}
        </select>
      </div>
      <div className={v2 ? "sx-field" : "field"}>
        <label htmlFor="report-type">Type</label>
        <select id="report-type" value={type ?? ""} onChange={(e) => setFilter("type", e.target.value)}>
          <option value="">All types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {reportTypeLabel[t]}
            </option>
          ))}
        </select>
      </div>
    </div>
  );

  if (v2) {
    return (
      <div className="sx-page">
        <h1>Reports</h1>
        <p className="sx-muted">
          Your gap reports and interview debriefs, grouped by target role. The role with the newest report comes first.
        </p>
        {filters}
        <section aria-label="Report list" className="sx-stack">
          {reports.isPending && <Loading label="Loading your reports" />}
          {reports.isError && <ErrorNotice error={reports.error} />}
          {reports.data && <ReportsByRole reports={reports.data} />}
        </section>
        <StoriesToWorkOn />
      </div>
    );
  }

  return (
    <>
      <PageHead title="Reports">
        <p>Your gap reports and interview debriefs, newest first.</p>
      </PageHead>
      {filters}
      <section className="panel" aria-label="Report list">
        {reports.isPending && <Loading label="Loading your reports" />}
        {reports.isError && <ErrorNotice error={reports.error} />}
        {reports.data && <ReportList reports={reports.data} />}
      </section>
    </>
  );
}
