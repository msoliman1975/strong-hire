/**
 * IN-12: the CV check. Rule-based, deterministic and instant: no model calls, no network. The
 * page runs it on every edit. Each issue has a stable `key` built from its type and the fields
 * involved (roles by company and title, not by position), so an accepted issue stays accepted
 * when the user edits something else.
 */
import type { JobPosting, Resume } from "../../api/types";

type ResumeRole = Resume["roles"][number];

export type IssueGroup = "dates" | "detail" | "level" | "consistency" | "job";

/** Where Fix goes: a field on a role card, the summary, or the skills card. */
export type IssueTarget =
  | { section: "summary" }
  | { section: "skills" }
  | { section: "role"; role: number; field: "start" | "end" | "title" | "achievement" | "achievements"; item?: number };

export interface ResumeIssue {
  key: string;
  group: IssueGroup;
  /** "high" draws the red stripe; the rest are warnings or notes. */
  severity: "high" | "medium" | "low";
  title: string;
  /** One line under the title with the facts, for example the two dates. */
  detail: string;
  /** Why it matters, shown when the card is open. */
  why: string;
  fixLabel: string;
  acceptLabel: string;
  target: IssueTarget;
  /** Every role the issue is about, for the "N issues" chip on each role card. */
  roles: number[];
  /** A short note shown on the field itself while the role is open for editing. */
  fieldNote?: string;
  /** Achievement indexes the issue is about, marked on the role card. */
  items?: number[];
  /** Gaps only: the period, for the practice link. */
  gap?: { from: string; to: string };
}

export interface CheckOptions {
  /** This month as YYYY-MM. Injected so the checks stay deterministic. */
  today: string;
  /** The job the page was opened for, if any. */
  job?: Pick<JobPosting, "must_have_skills" | "level" | "level_label" | "title"> | null;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DATE = /^(\d{4})(?:-(0[1-9]|1[0-2]))?$/;

/** Gaps longer than this many months are reported. */
export const GAP_MONTHS = 3;
/** A summary shorter than this many words is "very short". */
export const SHORT_SUMMARY_WORDS = 12;

interface Parsed {
  year: number;
  month: number | null;
}

function parse(value: string | null | undefined): Parsed | null {
  const m = value ? DATE.exec(value.trim()) : null;
  return m ? { year: Number(m[1]), month: m[2] ? Number(m[2]) : null } : null;
}

/** Months since year 0. A year alone counts as January or December, whichever `side` asks for. */
function index(p: Parsed, side: "early" | "late"): number {
  return p.year * 12 + (p.month ?? (side === "early" ? 1 : 12)) - 1;
}

/** "Mar 2022", or "2014" for a year alone. */
export function formatDate(value: string | null | undefined): string {
  const p = parse(value);
  if (!p) return value ?? "";
  return p.month ? `${MONTHS[p.month - 1]} ${p.year}` : String(p.year);
}

/** "Mar 2022 to now · 2 years 7 months". The length is left out when a date is missing. */
export function formatSpan(start: string | null | undefined, end: string | null | undefined, today: string): string {
  const from = start ? formatDate(start) : "Start not given";
  const to = end ? formatDate(end) : "now";
  const length = spanLength(start, end, today);
  return length ? `${from} to ${to} · ${length}` : `${from} to ${to}`;
}

/** "2 years 7 months", "about 3 years" when a date has no month, "" when it cannot be worked out. */
export function spanLength(start: string | null | undefined, end: string | null | undefined, today: string): string {
  const s = parse(start);
  const e = parse(end ?? today);
  if (!s || !e) return "";
  if (s.month === null || e.month === null) {
    const years = e.year - s.year;
    if (years < 0) return "";
    return years === 0 ? "under a year" : `about ${plural(years, "year")}`;
  }
  // Both months count: Jan to Mar is 3 months.
  const months = index(e, "late") - index(s, "early") + 1;
  if (months <= 0) return "";
  const y = Math.floor(months / 12);
  const m = months % 12;
  return [y ? plural(y, "year") : "", m ? plural(m, "month") : ""].filter(Boolean).join(" ");
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

/** Company names compared loosely: "Acme Inc." and "ACME" are the same company. */
const companyKey = (company: string) =>
  slug(company.replace(/\b(inc|llc|ltd|limited|gmbh|corp|corporation|co|plc|sa|ag)\b\.?/gi, "")) || slug(company);

/** A stable id per role: company and title, with a counter when the same pair repeats. */
export function roleIds(roles: Pick<ResumeRole, "company" | "title">[]): string[] {
  const seen = new Map<string, number>();
  return roles.map((r) => {
    const base = `${companyKey(r.company) || "role"}/${slug(r.title) || "untitled"}`;
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return n === 1 ? base : `${base}#${n}`;
  });
}

const roleName = (r: Pick<ResumeRole, "company" | "title">) => r.company.trim() || r.title.trim() || "this role";

/** A number, a percent, money or a result verb: the achievement says what changed. */
const RESULT =
  /\d|%|\$|€|£|\b(one|two|three|four|five|six|seven|eight|nine|ten|twice|half|third|quarter|double[ds]?|tripled?|halved)\b|\b(cut|reduc|increas|grew|rais|sav|lower|boost|doubl|fell|dropp|decreas|accelerat|shorten)\w*/i;
const NUMBER = /\d|%|\$|€|£/;
const WE = /\b(we|our|us)\b/i;
const I = /\b(i|my|me)\b|^\s*(led|built|owned|designed|drove|ran|wrote|managed|created|launched|shipped|hired|cut|grew|started|founded|mentored|coached)\b/i;
const SCOPE =
  /\b(team of|teams?|engineers|reports|direct reports|hired|managed|mentor\w*|coach\w*|budget|\$\d|million|cross[- ](team|functional)|org(anization)?[- ]wide|company[- ]wide|across \w+ teams|stakeholders|roadmap|strategy|headcount|led)\b/i;
const SENIOR_TITLE = /\b(senior|sr\.?|staff|principal|lead|head|director|vp|chief|architect)\b/i;

function seniorTarget(job: CheckOptions["job"], roles: ResumeRole[]): string | null {
  if (job?.level === "senior" || job?.level === "staff_principal") return job.level_label || (job.level === "senior" ? "Senior" : "Staff");
  if (job?.level) return null;
  if (job?.title && SENIOR_TITLE.test(job.title)) return job.title;
  if (!job && roles[0] && SENIOR_TITLE.test(roles[0].title)) return roles[0].title;
  return null;
}

/** Does the CV mention the skill anywhere: skills, role skills, achievements, titles or the summary? */
function mentions(resume: Resume, skill: string): boolean {
  const needle = skill.trim().toLowerCase();
  if (!needle) return true;
  const word = new RegExp(`(^|[^a-z0-9+#])${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^a-z0-9+#])`, "i");
  const texts = [
    resume.summary ?? "",
    ...resume.skills,
    ...resume.roles.flatMap((r) => [r.title, ...r.skills, ...r.achievements]),
    ...resume.certifications,
  ];
  return texts.some((t) => word.test(t));
}

interface Span {
  role: number;
  start: number;
  end: number;
}

/** Runs every check. Roles keep their order and indexes, so `target.role` points into `resume.roles`. */
export function checkResume(resume: Resume, options: CheckOptions): ResumeIssue[] {
  const issues: ResumeIssue[] = [];
  const today = parse(options.today);
  if (!today) throw new Error(`today must be YYYY-MM, got ${options.today}`);
  const now = index(today, "late");
  const roles = resume.roles;
  const ids = roleIds(roles);

  // ---- Dates, one role at a time.
  roles.forEach((r, i) => {
    const s = parse(r.start);
    const e = parse(r.end);
    const name = roleName(r);
    if (s && e && index(e, "late") < index(s, "early")) {
      issues.push({
        key: `dates.end-before-start:${ids[i]}`,
        group: "dates",
        severity: "high",
        title: `${name} ends before it starts`,
        detail: `${formatDate(r.start)} to ${formatDate(r.end)}`,
        why: "An end date before the start date looks like a typo, and screeners notice.",
        fixLabel: "Fix the date",
        acceptLabel: "Accept as it is",
        target: { section: "role", role: i, field: "end" },
        roles: [i],
        fieldNote: "Ends before it starts",
      });
    }
    for (const side of ["start", "end"] as const) {
      const p = side === "start" ? s : e;
      if (p && (p.month ? index(p, "early") : p.year * 12) > now) {
        issues.push({
          key: `dates.future:${ids[i]}:${side}`,
          group: "dates",
          severity: "high",
          title: `A future date on ${name}`,
          detail: `${side === "start" ? "Starts" : "Ends"} ${formatDate(r[side])}`,
          why: "Dates after today read as a mistake. If the role is current, leave the end empty.",
          fixLabel: "Fix the date",
          acceptLabel: "Accept as it is",
          target: { section: "role", role: i, field: side },
          roles: [i],
          fieldNote: "This date is in the future",
        });
      }
    }
    if ((s && s.month === null) || (e && e.month === null)) {
      issues.push({
        key: `dates.year-only:${ids[i]}`,
        group: "dates",
        severity: "low",
        title: `Years only on ${name}`,
        detail: `${formatDate(r.start) || "?"} to ${r.end ? formatDate(r.end) : "now"}`,
        why: "Years alone can hide up to 11 months on each side. Screeners often ask for the months.",
        fixLabel: "Add the months",
        acceptLabel: "Accept, years are enough",
        target: { section: "role", role: i, field: s && s.month === null ? "start" : "end" },
        roles: [i],
        fieldNote: "Add the month, for example 2016-04",
      });
    }
    if (!s) {
      issues.push({
        key: `dates.missing-start:${ids[i]}`,
        group: "dates",
        severity: "medium",
        title: `No start date on ${name}`,
        detail: "We could not find when this role started.",
        why: "Without dates, interviewers cannot tell how long you held the role.",
        fixLabel: "Add the date",
        acceptLabel: "Accept as it is",
        target: { section: "role", role: i, field: "start" },
        roles: [i],
        fieldNote: "Add a start date",
      });
    }
  });

  // ---- Dates across roles: overlaps and gaps. Years alone are read in the role's favor.
  const spans: Span[] = [];
  roles.forEach((r, i) => {
    const s = parse(r.start);
    if (!s) return;
    const e = r.end ? parse(r.end) : today;
    if (!e) return;
    spans.push({ role: i, start: index(s, "early"), end: r.end ? index(e, "late") : now });
  });

  for (let a = 0; a < spans.length; a++) {
    for (let b = a + 1; b < spans.length; b++) {
      const x = roles[spans[a].role];
      const y = roles[spans[b].role];
      // Strict reading for overlaps: a year alone counts as its latest start and earliest end.
      const strict = (r: ResumeRole) => {
        const s = parse(r.start)!;
        const e = r.end ? parse(r.end) : today;
        return { start: index(s, "late"), end: r.end && e ? index(e, "early") : now };
      };
      const p = strict(x);
      const q = strict(y);
      const months = Math.min(p.end, q.end) - Math.max(p.start, q.start);
      // A one-month handover is normal.
      if (months < 2) continue;
      const [first, second] = p.start <= q.start ? [spans[a].role, spans[b].role] : [spans[b].role, spans[a].role];
      const earlier = roles[first];
      const later = roles[second];
      const pair = [ids[first], ids[second]].sort().join("+");
      const both = !x.end && !y.end;
      issues.push({
        key: `dates.overlap:${pair}`,
        group: "dates",
        severity: "high",
        title: both ? "Two current roles" : "Overlapping roles",
        detail: both
          ? `${roleName(earlier)} and ${roleName(later)} both have no end date`
          : `${roleName(earlier)} ends ${earlier.end ? formatDate(earlier.end) : "now"}, ${roleName(later)} starts ${formatDate(later.start)}`,
        why: "Interviewers ask about overlaps. If you really held both, say so; otherwise fix the date.",
        fixLabel: "Fix the date",
        acceptLabel: "Accept: I held both",
        target: { section: "role", role: first, field: "end" },
        roles: [first, second],
        fieldNote: `Overlaps ${roleName(later)} by ${plural(months, "month")}`,
      });
    }
  }

  // Gaps: merge the spans in time order; a gap is a stretch no role covers.
  const ordered = [...spans].sort((p, q) => p.start - q.start || p.end - q.end);
  let cover: Span | null = null;
  for (const span of ordered) {
    if (cover) {
      const months = span.start - cover.end - 1;
      if (months > GAP_MONTHS) {
        const before = roles[cover.role];
        const after = roles[span.role];
        issues.push({
          key: `dates.gap:${ids[cover.role]}>${ids[span.role]}`,
          group: "dates",
          severity: "medium",
          title: `A ${months}-month gap`,
          detail: `${formatDate(before.end)} to ${formatDate(after.start)}, between ${roleName(before)} and ${roleName(after)}`,
          why: "Gaps over 3 months come up in screens. Check the dates, or accept it and practice your answer (study, travel, caring, a career break).",
          fixLabel: "Check the dates",
          acceptLabel: "Accept, I'll explain it",
          target: { section: "role", role: span.role, field: "start" },
          roles: [cover.role, span.role],
          gap: { from: formatDate(before.end), to: formatDate(after.start) },
        });
      }
    }
    if (!cover || span.end > cover.end) cover = span;
  }

  // A current role not marked: nothing is current, and the newest role ended this month or last.
  if (roles.length > 0 && roles.every((r) => r.end)) {
    let newest = -1;
    let newestEnd = -Infinity;
    roles.forEach((r, i) => {
      const e = parse(r.end);
      if (e && index(e, "late") > newestEnd) {
        newestEnd = index(e, "late");
        newest = i;
      }
    });
    if (newest >= 0 && newestEnd >= now - 1 && newestEnd <= now) {
      const r = roles[newest];
      issues.push({
        key: `dates.current-not-marked:${ids[newest]}`,
        group: "dates",
        severity: "medium",
        title: `Is ${roleName(r)} your current role?`,
        detail: `It ends ${formatDate(r.end)}, and no role is marked current.`,
        why: "If you still work there, leave the end date empty so interviewers read it as your current job.",
        fixLabel: "Mark as current",
        acceptLabel: "Accept, I left",
        target: { section: "role", role: newest, field: "end" },
        roles: [newest],
        fieldNote: "Leave empty if you still work here",
      });
    }
  }

  // ---- Detail.
  roles.forEach((r, i) => {
    const name = roleName(r);
    const items = r.achievements.map((a) => a.trim()).filter(Boolean);
    if (items.length < 2) {
      issues.push({
        key: `detail.few-achievements:${ids[i]}`,
        group: "detail",
        severity: "medium",
        title: items.length === 0 ? `No achievements on ${name}` : `One achievement on ${name}`,
        detail: "Roles read best with 2 to 5 achievements.",
        why: "Interviewers pick their questions from your achievements. A thin role gives them little to ask about, and you little to show.",
        fixLabel: "Add an achievement",
        acceptLabel: "Accept as it is",
        target: { section: "role", role: i, field: "achievements" },
        roles: [i],
      });
    }
    const noResult = r.achievements.flatMap((a, j) => (a.trim() && !RESULT.test(a) ? [j] : []));
    if (noResult.length > 0) {
      issues.push({
        key: `detail.no-result:${ids[i]}`,
        group: "detail",
        severity: "low",
        title:
          noResult.length === 1
            ? `An achievement without a result at ${name}`
            : `${noResult.length} achievements without a result at ${name}`,
        detail: `"${truncate(r.achievements[noResult[0]], 60)}"`,
        why: "Say what changed: a number, a percent, time saved or who it helped. Results are what interviewers remember.",
        fixLabel: "Add a result",
        acceptLabel: "Accept as it is",
        target: { section: "role", role: i, field: "achievement", item: noResult[0] },
        roles: [i],
        items: noResult,
        fieldNote: "No result or number. Add what changed?",
      });
    }
    const we = r.achievements.filter((a) => WE.test(a));
    if (we.length > 0 && !r.achievements.some((a) => I.test(a))) {
      const j = r.achievements.findIndex((a) => WE.test(a));
      issues.push({
        key: `detail.we-no-i:${ids[i]}`,
        group: "detail",
        severity: "low",
        title: `"We" but never "I" at ${name}`,
        detail: `"${truncate(r.achievements[j], 60)}"`,
        why: "Interviewers want your part. Say what you did, then what the team achieved.",
        fixLabel: "Say what you did",
        acceptLabel: "Accept as it is",
        target: { section: "role", role: i, field: "achievement", item: j },
        roles: [i],
        items: r.achievements.flatMap((a, k) => (WE.test(a) ? [k] : [])),
        fieldNote: 'Says "we". What was your part?',
      });
    }
  });

  const summary = (resume.summary ?? "").trim();
  const words = summary ? summary.split(/\s+/).length : 0;
  if (!summary) {
    issues.push({
      key: "detail.summary-missing",
      group: "detail",
      severity: "medium",
      title: "No summary",
      detail: "Your CV has no intro.",
      why: '"Tell me about yourself" opens most interviews. Two or three lines here give you a ready answer.',
      fixLabel: "Write a summary",
      acceptLabel: "Accept, no summary",
      target: { section: "summary" },
      roles: [],
    });
  } else if (words < SHORT_SUMMARY_WORDS) {
    issues.push({
      key: "detail.summary-short",
      group: "detail",
      severity: "low",
      title: "A very short summary",
      detail: `${plural(words, "word")}.`,
      why: "Say who you are, your years and field, and one result. It sets up your answer to \"tell me about yourself\".",
      fixLabel: "Add to the summary",
      acceptLabel: "Accept as it is",
      target: { section: "summary" },
      roles: [],
      fieldNote: "Very short",
    });
  } else if (!NUMBER.test(summary)) {
    issues.push({
      key: "detail.summary-no-number",
      group: "detail",
      severity: "low",
      title: "Summary has no number",
      detail: "No years, size or result in your intro.",
      why: "One number (years, team size, a result) makes the intro concrete.",
      fixLabel: "Add a number",
      acceptLabel: "Accept as it is",
      target: { section: "summary" },
      roles: [],
      fieldNote: "No number in your summary",
    });
  }

  // ---- Fit for level.
  const target = seniorTarget(options.job, roles);
  if (target) {
    const texts = [summary, ...roles.flatMap((r) => r.achievements)];
    if (!texts.some((t) => SCOPE.test(t))) {
      issues.push({
        key: "level.no-scope",
        group: "level",
        severity: "medium",
        title: "No scope for a senior role",
        detail: `Target: ${target}. No team size, budget or cross-team work.`,
        why: "Senior interviews test scope. Show how many people, teams or how much money your work touched.",
        fixLabel: "Add scope",
        acceptLabel: "Accept as it is",
        target: roles.length > 0 ? { section: "role", role: 0, field: "achievements" } : { section: "summary" },
        roles: roles.length > 0 ? [0] : [],
      });
    }
  }

  // ---- Consistency.
  const listed = new Set(resume.skills.map((s) => s.trim().toLowerCase()));
  const used: string[] = [];
  for (const r of roles) {
    for (const s of r.skills) {
      const k = s.trim().toLowerCase();
      if (k && !listed.has(k) && !used.some((u) => u.toLowerCase() === k)) used.push(s.trim());
    }
  }
  if (used.length > 0) {
    issues.push({
      key: `consistency.skills-missing:${used.map(slug).sort().join(",")}`,
      group: "consistency",
      severity: "low",
      title: used.length === 1 ? "A skill missing from Skills" : `${used.length} skills missing from Skills`,
      detail: used.join(", "),
      why: "Recruiters and match tools read the Skills list first. Skills you used in a role belong there too.",
      fixLabel: "Open Skills",
      acceptLabel: "Accept as it is",
      target: { section: "skills" },
      roles: [],
    });
  }

  const byCompany = new Map<string, number[]>();
  roles.forEach((r, i) => {
    const k = companyKey(r.company);
    if (k) byCompany.set(k, [...(byCompany.get(k) ?? []), i]);
  });
  for (const [company, list] of byCompany) {
    if (list.length < 2) continue;
    issues.push({
      key: `consistency.same-company:${company}`,
      group: "consistency",
      severity: "low",
      title: `${roles[list[0]].company} listed ${list.length} times`,
      detail: list.map((i) => roles[i].title).join(", "),
      why: "If these are promotions, interviewers like seeing them under one company. If one is a duplicate, remove it.",
      fixLabel: "Open the role",
      acceptLabel: "Accept: separate roles",
      target: { section: "role", role: list[1], field: "title" },
      roles: list,
    });
  }

  // ---- Against a job.
  const missing = (options.job?.must_have_skills ?? []).filter((s) => s.trim() && !mentions(resume, s));
  if (missing.length > 0) {
    issues.push({
      key: `job.must-have:${missing.map(slug).sort().join(",")}`,
      group: "job",
      severity: "medium",
      title:
        missing.length === 1 ? "A must-have skill the CV never shows" : `${missing.length} must-have skills the CV never shows`,
      detail: missing.join(", "),
      why: "The job lists these as must-haves. If you have them, add them to Skills or to an achievement; if not, prepare to talk about it.",
      fixLabel: "Open Skills",
      acceptLabel: "Accept, I'll address it",
      target: { section: "skills" },
      roles: [],
    });
  }

  // Most serious first; the sort is stable, so ties keep the order above.
  return issues.sort((a, b) => SEVERITY[a.severity] - SEVERITY[b.severity]);
}

const SEVERITY: Record<ResumeIssue["severity"], number> = { high: 0, medium: 1, low: 2 };

function truncate(text: string, max: number): string {
  const t = text.trim();
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

/** Skills grouped as tools, domain and ways of working, for lists over 10 (the design's rule). */
export const GROUP_SKILLS_OVER = 10;

const TOOLS =
  /\b(sql|python|java|javascript|typescript|go|golang|rust|ruby|php|scala|kotlin|swift|c\+\+|c#|r|excel|sheets|tableau|looker|power ?bi|figma|sketch|jira|confluence|notion|git|github|docker|kubernetes|aws|gcp|azure|terraform|react|vue|angular|node(\.js)?|django|flask|spring|postgres(ql)?|mysql|mongodb|redis|kafka|spark|airflow|dbt|snowflake|bigquery|salesforce|hubspot|amplitude|mixpanel|segment|linux|graphql|html|css)\b/i;
const WAYS =
  /\b(stakeholder|communication|leadership|mentor|coaching|agile|scrum|kanban|collaborat|facilitat|negotiat|presentation|public speaking|management|hiring|prioriti|roadmap|planning|strategy|teamwork|cross[- ]functional|discovery|user research|a\/b testing|experimentation|okrs?)/i;

export type SkillGroup = "Tools" | "Domain" | "Ways of working";

export function groupSkills(skills: string[]): { group: SkillGroup; skills: string[] }[] {
  const groups: Record<SkillGroup, string[]> = { Tools: [], Domain: [], "Ways of working": [] };
  for (const s of skills) {
    if (TOOLS.test(s)) groups.Tools.push(s);
    else if (WAYS.test(s)) groups["Ways of working"].push(s);
    else groups.Domain.push(s);
  }
  return (["Tools", "Domain", "Ways of working"] as const)
    .filter((g) => groups[g].length > 0)
    .map((g) => ({ group: g, skills: groups[g] }));
}

/** Roles sorted newest first: current roles, then by end, then by start. Undated roles go last. */
export function newestFirst<T extends Pick<ResumeRole, "start" | "end">>(roles: T[]): T[] {
  const end = (r: T) => (r.end ? parse(r.end) : null);
  const score = (r: T) => {
    if (!r.end) return parse(r.start) ? Number.MAX_SAFE_INTEGER - 1 : -1;
    const e = end(r);
    return e ? index(e, "late") : -1;
  };
  const start = (r: T) => {
    const s = parse(r.start);
    return s ? index(s, "early") : -1;
  };
  return [...roles].sort((a, b) => score(b) - score(a) || start(b) - start(a));
}

/** This month as YYYY-MM. */
export function thisMonth(date = new Date()): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
