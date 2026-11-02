/**
 * RH-4 (mockup #rehearse): Strova as the interviewer, the recommended next take, then every
 * interview across the target roles with its readiness and Retake or Start.
 * RMAP-1: a "Target role" filter (All by default) narrows the list and the recommendation to one
 * role. It lives in the URL (?role=<id>), so Back and a shared link keep it.
 */
import { Link, useSearchParams } from "react-router";

import { useRehearsals } from "../../api/roles";
import type { RehearsalItem } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { DEFAULT_TAKE_MINUTES, interviewPath, takesMeta, typeName } from "../roles/shared";

const GOAL = 75;

function company(item: RehearsalItem): string {
  return item.role.company_name ?? item.role.name ?? "Role";
}

/** Why this take: the date first, then the gap to the goal. */
function why(item: RehearsalItem): string {
  const parts: string[] = [];
  if (item.role.days_left !== null && item.role.days_left >= 0) parts.push("Closest to your interview date");
  const score = item.readiness.score;
  if (score === null) parts.push("your first Realistic take sets your starting readiness");
  else parts.push(`${GOAL - score} points from your readiness goal`);
  const text = parts.join(", and ");
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
}

/** "Rubrik · Staff Engineer": the company, and the title when there is one. */
function roleLabel(item: RehearsalItem): string {
  const title = item.role.title;
  return title && title !== company(item) ? `${company(item)} · ${title}` : company(item);
}

/**
 * RMAP-1: the recommended take among some interviews, with the API's rule (RH-4, `recommend` in
 * strong_api/plan/interviews.py): below the goal only, the closest interview date first, then the
 * lowest readiness (no score yet counts lowest), then the oldest interview.
 */
export function recommendNext(items: readonly RehearsalItem[]): RehearsalItem | null {
  const below = items.filter((i) => i.readiness.score === null || i.readiness.score < GOAL);
  const sorted = [...below].sort(
    (a, b) =>
      Number(a.role.interview_date === null) - Number(b.role.interview_date === null) ||
      (a.role.interview_date ?? "").localeCompare(b.role.interview_date ?? "") ||
      (a.readiness.score ?? -1) - (b.readiness.score ?? -1) ||
      a.interview.created_at.localeCompare(b.interview.created_at),
  );
  return sorted[0] ?? null;
}

/** The roles the interviews belong to, in the list's order, each with its interview count. */
function rolesOf(items: readonly RehearsalItem[]) {
  const roles = new Map<string, { id: string; label: string; company: string; count: number }>();
  for (const item of items) {
    const found = roles.get(item.role.id);
    if (found) found.count += 1;
    else roles.set(item.role.id, { id: item.role.id, label: roleLabel(item), company: company(item), count: 1 });
  }
  return [...roles.values()];
}

export function RehearsalsPage() {
  const data = useRehearsals();
  const [params, setParams] = useSearchParams();
  const all = data.data?.items ?? [];
  const roles = rolesOf(all);
  // A role that is gone (archived, deleted) or a bad link shows everything.
  const roleId = roles.some((r) => r.id === params.get("role")) ? params.get("role") : null;
  const items = roleId ? all.filter((i) => i.role.id === roleId) : all;
  // RMAP-1: two roles at one company would give identical rows ("Rubrik · Behavioral"), so their
  // rows name the role title too.
  const companyRoles = new Map<string, number>();
  for (const r of roles) companyRoles.set(r.company, (companyRoles.get(r.company) ?? 0) + 1);
  const rowTitle = (item: RehearsalItem) =>
    (companyRoles.get(company(item)) ?? 0) > 1 ? roleLabel(item) : company(item);
  const next = roleId
    ? recommendNext(items)
    : (all.find((i) => i.interview.id === data.data?.next_interview_id) ?? null);
  const pick = (id: string) =>
    setParams(
      (p) => {
        const out = new URLSearchParams(p);
        if (id) out.set("role", id);
        else out.delete("role");
        return out;
      },
      { replace: true },
    );
  return (
    <div className="sx-page">
      <div className="sx-row">
        <Strova mode="interviewing" size={72} />
        <div>
          <h1>Rehearsals with Strova</h1>
          <p className="sx-muted sx-small">
            Rehearse every interview across your target roles with Strova, who plays the interviewer.
          </p>
        </div>
      </div>
      {roles.length > 1 && (
        <div className="sx-row" style={{ gap: 8 }}>
          <label htmlFor="rehearsals-role" className="sx-small" style={{ fontWeight: 600 }}>
            Target role
          </label>
          <select
            id="rehearsals-role"
            value={roleId ?? ""}
            onChange={(e) => pick(e.target.value)}
            style={{ width: "auto", maxWidth: "100%" }}
          >
            <option value="">All target roles ({all.length})</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label} ({r.count})
              </option>
            ))}
          </select>
        </div>
      )}
      {data.isPending && <Loading label="Loading your rehearsals" />}
      {data.isError && <ErrorNotice error={data.error} />}
      {next && (
        <section className="sx-hero" aria-label="Recommended next take">
          <span className="sx-eyebrow" style={{ color: "var(--sh-teal-light)" }}>
            Recommended next take
          </span>
          <div className="big">
            {rowTitle(next)} · {typeName(next.interview)}, Realistic, {DEFAULT_TAKE_MINUTES} minutes
          </div>
          <div className="sub">{why(next)}</div>
          <div className="sx-row">
            <Link className="sx-btn" to={interviewPath(next.interview.id)}>
              {next.takes_count === 0 ? "Start the first take" : "Start the take"}
            </Link>
          </div>
        </section>
      )}
      {data.data && data.data.items.length === 0 && (
        <div className="sx-card dashed">
          <h2>No interviews yet</h2>
          <p className="sx-small sx-muted">Add a target role and keep the interviews Strova suggests.</p>
          <div className="sx-row">
            <Link className="sx-btn ghost sm" to="/roles/new">
              Add a target role
            </Link>
          </div>
        </div>
      )}
      {roleId && !next && items.length > 0 && (
        <p className="sx-notice ground" role="status">
          Every interview for this role is at your readiness goal. Retake any of them to stay sharp.
        </p>
      )}
      {items.length > 0 && (
        <div className="sx-card" data-testid="rehearsal-list">
          {items.map((item) => {
            const score = item.readiness.score;
            return (
              <Link key={item.interview.id} className="sx-list-row" to={interviewPath(item.interview.id)}>
                <div className="sx-stack" style={{ gap: 4, flex: "1 1 300px" }}>
                  <strong>
                    {rowTitle(item)} · {typeName(item.interview)}
                  </strong>
                  <span className="sx-small sx-muted">{takesMeta(item)}</span>
                </div>
                <div style={{ flex: "0 1 220px", minWidth: 140 }}>
                  <div className="sx-between sx-small">
                    <span className="sx-muted">Readiness</span>
                    <span className="sx-mono">{score ?? "–"}</span>
                  </div>
                  <div className="sx-bar">
                    <span style={{ width: `${score ?? 0}%` }} />
                  </div>
                </div>
                <span className={`sx-btn sm${score === null ? " ghost" : ""}`}>{item.takes_count === 0 ? "Start" : "Retake"}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
