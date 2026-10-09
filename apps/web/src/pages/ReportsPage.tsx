import { useSearchParams } from "react-router";

import { useJobs, useReports } from "../api/hooks";
import type { ReportType } from "../api/types";
import { ReportList, reportTypeLabel } from "../components/ReportList";
import { ErrorNotice, Loading, PageHead } from "../components/ui";

const TYPES = Object.keys(reportTypeLabel) as ReportType[];

/** R1: every gap report and interview debrief, newest first, filtered by job and by type. */
export function ReportsPage() {
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

  return (
    <>
      <PageHead title="Reports">
        <p>Your gap reports and interview debriefs, newest first.</p>
      </PageHead>
      <div className="row section" role="group" aria-label="Filters">
        <div className="field">
          <label htmlFor="report-job">Job</label>
          <select id="report-job" value={jobId ?? ""} onChange={(e) => setFilter("job", e.target.value)}>
            <option value="">All jobs</option>
            {(jobs.data ?? []).map((j) => (
              <option key={j.job_target.id} value={j.job_target.id}>
                {j.job_target.name ?? "Job"}
              </option>
            ))}
            {filterJobMissing && <option value={jobId}>Deleted job</option>}
          </select>
        </div>
        <div className="field">
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
      <section className="panel" aria-label="Report list">
        {reports.isPending && <Loading label="Loading your reports" />}
        {reports.isError && <ErrorNotice error={reports.error} />}
        {reports.data && <ReportList reports={reports.data} />}
      </section>
    </>
  );
}
