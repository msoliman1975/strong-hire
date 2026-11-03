/**
 * NV-4 (v2 Reports): gap reports and interview debriefs grouped by target role, on the shared
 * card shell (RSD-5) the Resumes list and Target roles use. One SummaryCard per role: the role
 * title and the date of its latest report; tiles for the latest match, gap reports and debriefs;
 * the resume line; the reports, newest first; and a footer link to the target role.
 */
import { useState } from "react";
import { Link } from "react-router";

import type { ReportItem } from "../../api/types";
import { reportPath } from "../../api/reports";
import { reportSummary, reportTypeLabel, RESUME_DELETED } from "../../components/ReportList";
import { SummaryCard, type StatTileProps } from "../../components/ux/SummaryCard";
import "../../components/ux/ux.css";
import { formatDate } from "../../labels";
import { rolePath } from "../roles/shared";

/** A role card shows this many reports before "Show all". */
export const REPORTS_PER_CARD = 3;

export const ROLE_DELETED = "Target role deleted";

export interface RoleReports {
  jobTargetId: string;
  title: string;
  deleted: boolean;
  /** Newest first, as the API sends them. */
  reports: ReportItem[];
}

/** Groups the reports by target role. The role with the newest report comes first. */
export function groupByRole(reports: ReportItem[]): RoleReports[] {
  const groups = new Map<string, RoleReports>();
  for (const r of reports) {
    let g = groups.get(r.job_target_id);
    if (!g) {
      g = {
        jobTargetId: r.job_target_id,
        title: r.job_deleted ? ROLE_DELETED : (r.job_name ?? "Target role"),
        deleted: r.job_deleted,
        reports: [],
      };
      groups.set(r.job_target_id, g);
    }
    g.reports.push(r);
  }
  return [...groups.values()];
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

/** The latest match score, the number of gap reports and the number of debriefs ("—" when unknown). */
export function reportStats(reports: ReportItem[]): readonly [StatTileProps, StatTileProps, StatTileProps] {
  const gaps = reports.filter((r) => r.type === "gap_report");
  const debriefs = reports.length - gaps.length;
  const match = gaps[0]?.match_score;
  return [
    { value: match ?? "—", label: "latest match" },
    { value: gaps.length, label: plural(gaps.length, "gap report", "gap reports") },
    { value: debriefs, label: plural(debriefs, "debrief", "debriefs") },
  ];
}

/** The resume of the latest report that names one. */
function resumeLine(reports: ReportItem[]): string {
  const r = reports.find((x) => x.resume_deleted || x.resume_name);
  if (!r) return "No resume on these reports";
  return r.resume_deleted ? RESUME_DELETED : `Resume: ${r.resume_name}`;
}

function RoleReportsCard({ group }: { group: RoleReports }) {
  const [all, setAll] = useState(false);
  const shown = all ? group.reports : group.reports.slice(0, REPORTS_PER_CARD);
  const hidden = group.reports.length - shown.length;
  return (
    <SummaryCard
      title={group.title}
      chip={<span className="sx-chip">Latest {formatDate(group.reports[0].at)}</span>}
      stats={reportStats(group.reports)}
      meta={resumeLine(group.reports)}
      primary={
        group.deleted ? undefined : (
          <Link className="sx-btn sm" to={rolePath(group.jobTargetId)} aria-label={`Open target role: ${group.title}`}>
            Open target role
          </Link>
        )
      }
      actions={
        hidden > 0 || all ? (
          <button type="button" className="sx-btn quiet sm" aria-expanded={all} onClick={() => setAll((a) => !a)}>
            {all ? "Show fewer" : `Show all ${group.reports.length}`}
          </button>
        ) : undefined
      }
    >
      <ul className="plain-list" aria-label={`Reports for ${group.title}`} style={{ margin: 0, padding: 0 }}>
        {shown.map((r) => (
          <li key={`${r.type}-${r.id}`} className="sx-list-row" style={{ padding: "8px 0", flexWrap: "nowrap" }}>
            <div style={{ minWidth: 0 }}>
              <Link to={reportPath(r)}>
                <strong>{reportTypeLabel[r.type]}</strong>
              </Link>
              <p className="sx-small sx-muted">{reportSummary(r, true)}</p>
            </div>
            <span className="sx-small sx-muted" style={{ flexShrink: 0 }}>
              {formatDate(r.at)}
            </span>
          </li>
        ))}
      </ul>
    </SummaryCard>
  );
}

export function ReportsByRole({ reports }: { reports: ReportItem[] }) {
  if (reports.length === 0) {
    return (
      <div className="sx-card dashed">
        <h2>No reports yet</h2>
        <p className="sx-small sx-muted">
          A gap report appears when Strova measures your resume against a target role, and a debrief after each take.
        </p>
      </div>
    );
  }
  return (
    <div className="sx-grid2 stretch">
      {groupByRole(reports).map((g) => (
        <RoleReportsCard key={g.jobTargetId} group={g} />
      ))}
    </div>
  );
}
