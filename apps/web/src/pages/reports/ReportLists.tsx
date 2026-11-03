/**
 * NV-4 (v2 Reports): three plain lists, one at a time: gap reports, interview debriefs and
 * stories. Each row is a link to its page and carries its key data: the target role, resume and
 * match for a gap report; the role, interview, mode, length and result for a debrief; the style,
 * skills, last edit and status for a story.
 */
import type { ReactNode } from "react";
import { Link } from "react-router";

import { reportPath } from "../../api/reports";
import type { ReportItem } from "../../api/types";
import { jobLabel, RESUME_DELETED } from "../../components/ReportList";
import { competencyLabel, formatDate, interviewTypeLabel, modeLabels } from "../../labels";
import type { Story } from "../stories/api";
import { displayStatusLabel } from "../stories/api";
import { storyPath } from "../stories/paths";
import "./reports.css";

export type ReportsView = "gap_report" | "interview_debrief" | "stories";

export const VIEWS: readonly { view: ReportsView; label: string }[] = [
  { view: "gap_report", label: "Gap reports" },
  { view: "interview_debrief", label: "Interview debriefs" },
  { view: "stories", label: "Stories" },
];

/** The view from `?type=`; old links with a report type keep working. Gap reports by default. */
export const parseView = (value: string | null): ReportsView =>
  VIEWS.find((v) => v.view === value)?.view ?? "gap_report";

const STYLE_LABEL: Record<string, string> = { star: "STAR", carl: "CARL" };

/** "Scoring", "Scoring failed", or the hire signal of a ready debrief. */
export function debriefResult(r: ReportItem): { text: string; tone: "ok" | "warn" | "bad" | "plain" } {
  if (r.status === "failed") return { text: "Scoring failed", tone: "bad" };
  if (r.status !== "ready") return { text: "Scoring", tone: "plain" };
  const signal = r.hire_signal ?? "Ready";
  const tone = /^(Strong Hire|Hire)$/i.test(signal) ? "ok" : /No Hire/i.test(signal) ? "bad" : "warn";
  return { text: signal, tone };
}

function Row({
  to,
  label,
  title,
  meta,
  aside,
  date,
}: {
  to: string;
  label: string;
  title: string;
  meta: string;
  aside: ReactNode;
  date: string;
}) {
  return (
    <li>
      <Link className="rp-row" to={to} aria-label={label}>
        <span className="rp-row__main">
          <strong className="rp-row__title">{title}</strong>
          <span className="rp-row__meta">{meta}</span>
        </span>
        <span className="rp-row__aside">
          {aside}
          <span className="rp-row__date">{date}</span>
        </span>
      </Link>
    </li>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="sx-card dashed">
      <p className="sx-small sx-muted">{children}</p>
    </div>
  );
}

export function GapReportList({ reports }: { reports: ReportItem[] }) {
  if (reports.length === 0)
    return <Empty>No gap reports yet. One appears when Strova measures a resume against a target role.</Empty>;
  return (
    <ul className="rp-list" aria-label="Gap reports">
      {reports.map((r) => {
        const role = jobLabel(r);
        const resume = r.resume_deleted ? RESUME_DELETED : r.resume_name ? `Resume: ${r.resume_name}` : "Resume";
        const match = r.match_score ?? null;
        return (
          <Row
            key={r.id}
            to={reportPath(r)}
            label={`Gap report: ${role}, ${match === null ? "match not known" : `match ${match}`}, ${formatDate(r.at)}`}
            title={role}
            meta={resume}
            aside={<span className="sx-chip t rp-score">{match === null ? "Match —" : `Match ${match}`}</span>}
            date={formatDate(r.at)}
          />
        );
      })}
    </ul>
  );
}

export function DebriefList({ reports }: { reports: ReportItem[] }) {
  if (reports.length === 0) return <Empty>No interview debriefs yet. One appears after each take.</Empty>;
  const modes = modeLabels(true).label;
  return (
    <ul className="rp-list" aria-label="Interview debriefs">
      {reports.map((r) => {
        const role = jobLabel(r);
        const meta = [
          r.interview_type ? interviewTypeLabel[r.interview_type] : "Interview",
          r.mode ? modes[r.mode] : null,
          r.duration_min ? `${r.duration_min} min` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        const result = debriefResult(r);
        return (
          <Row
            key={r.id}
            to={reportPath(r)}
            label={`Interview debrief: ${role}, ${meta}, ${result.text}, ${formatDate(r.at)}`}
            title={role}
            meta={meta}
            aside={<span className={`sx-chip${result.tone === "plain" ? "" : ` ${result.tone}`}`}>{result.text}</span>}
            date={formatDate(r.at)}
          />
        );
      })}
    </ul>
  );
}

/** Every story, the last edited first, with its status (ST-8). */
export function StoryList({ stories }: { stories: Story[] }) {
  if (stories.length === 0) return <Empty>No stories yet. Build your first one with Strova.</Empty>;
  const sorted = [...stories].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return (
    <ul className="rp-list" aria-label="Stories">
      {sorted.map((s) => {
        const skills = (s.skills ?? []).slice(0, 3).map(competencyLabel);
        const notes = s.notes?.length ?? 0;
        const meta = [
          s.style ? STYLE_LABEL[s.style] : "Classic",
          skills.length ? skills.join(", ") : null,
          notes ? `${notes} coach ${notes === 1 ? "note" : "notes"}` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        const status = displayStatusLabel[s.display_status];
        return (
          <Row
            key={s.id}
            to={storyPath(s.id)}
            label={`Story: ${s.title}, ${status}, edited ${formatDate(s.updated_at)}`}
            title={s.title}
            meta={meta}
            aside={<span className={`sx-chip${s.display_status === "proven" ? " ok" : s.display_status === "ready" ? " t" : ""}`}>{status}</span>}
            date={`Edited ${formatDate(s.updated_at)}`}
          />
        );
      })}
    </ul>
  );
}
