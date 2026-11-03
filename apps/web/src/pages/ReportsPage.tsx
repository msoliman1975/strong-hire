import { useSearchParams } from "react-router";

import { useJobs, useReports } from "../api/hooks";
import type { ReportType } from "../api/types";
import { ReportList, reportTypeLabel } from "../components/ReportList";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import "../components/ux/ux.css";
import { useFeature } from "../theme/features";
import "./home/StoryLibrary.css";
import { DebriefList, GapReportList, parseView, StoryList, VIEWS, type ReportsView } from "./reports/ReportLists";
import { useStories } from "./stories/api";

const TYPES = Object.keys(reportTypeLabel) as ReportType[];

/**
 * R1: every gap report and interview debrief, newest first, filtered by job and by type. With
 * `v2_enabled` on (NV-4) it is the last rail item, with three plain lists: gap reports, interview
 * debriefs and stories. Each row opens its page. The view is in `?type=`.
 */
export function ReportsPage() {
  const v2 = useFeature("v2_enabled");
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job") || null;
  const rawType = params.get("type");
  const type = TYPES.includes(rawType as ReportType) ? (rawType as ReportType) : null;
  // v2 shows the counts of every view, so it reads every report and splits them here.
  const reports = useReports({ jobTargetId: jobId, type: v2 ? null : type });
  const stories = useStories();
  const view: ReportsView = parseView(rawType);
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
    const gaps = (reports.data ?? []).filter((r) => r.type === "gap_report");
    const debriefs = (reports.data ?? []).filter((r) => r.type === "interview_debrief");
    const count: Record<ReportsView, number | undefined> = {
      gap_report: reports.data ? gaps.length : undefined,
      interview_debrief: reports.data ? debriefs.length : undefined,
      stories: stories.data?.length,
    };
    const roleFilter = (
      <div className="sx-field rp-filter">
        <label htmlFor="report-job">Target role</label>
        <select id="report-job" value={jobId ?? ""} onChange={(e) => setFilter("job", e.target.value)}>
          <option value="">All target roles</option>
          {(jobs.data ?? []).map((j) => (
            <option key={j.job_target.id} value={j.job_target.id}>
              {j.job_target.name ?? "Target role"}
            </option>
          ))}
          {filterJobMissing && <option value={jobId}>Deleted target role</option>}
        </select>
      </div>
    );
    const current = VIEWS.find((v) => v.view === view)?.label ?? "Reports";
    return (
      <div className="sx-page">
        <h1>Reports</h1>
        <p className="sx-muted">Your gap reports, interview debriefs and stories. Open one to see it in full.</p>
        <div className="sx-between">
          <div className="sx-seg rp-views" role="group" aria-label="Show">
            {VIEWS.map((v) => (
              <button
                key={v.view}
                type="button"
                aria-pressed={view === v.view}
                onClick={() => setFilter("type", v.view === "gap_report" ? "" : v.view)}
              >
                {v.label}
                {count[v.view] !== undefined ? ` · ${count[v.view]}` : ""}
              </button>
            ))}
          </div>
          {view !== "stories" && roleFilter}
        </div>
        <section aria-label={current} className="sx-stack">
          {view === "stories" ? (
            <>
              {stories.isPending && <Loading label="Loading your stories" />}
              {stories.isError && <ErrorNotice error={stories.error} title="Your stories did not load" />}
              {stories.data && <StoryList stories={stories.data} />}
            </>
          ) : (
            <>
              {reports.isPending && <Loading label="Loading your reports" />}
              {reports.isError && <ErrorNotice error={reports.error} />}
              {reports.data && (view === "gap_report" ? <GapReportList reports={gaps} /> : <DebriefList reports={debriefs} />)}
            </>
          )}
        </section>
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
