/**
 * MSW handler for U11's GET /me/plan, with the shape of strong_api.plan.personal. The plan is
 * built from the other mocked endpoints (rehearsals, stories, the main resume's issues and story
 * ideas, the profile's plan style) with the same rules as the API: rehearsal items below 75, story
 * skills without a Ready story, started Drafts, resume ideas and issues; the first open item is
 * next; the weekly style puts at most one item a day, Monday to Saturday.
 */
import { http, HttpResponse } from "msw/http";

import type {
  PersonalPlan,
  PlanGroup,
  PlanItem,
  Profile,
  Rehearsals,
  ResumeIssues,
  ResumeOut,
  StoryIdeasOut,
} from "../api/types";
import type { Story } from "../pages/stories/api";

const API = "*/api";
const GOAL = 75;
const STORY_SKILLS = ["ownership", "impact", "collaboration", "conflict_handling", "learning_from_failure", "communication"];
const PARTS = ["context", "stakes", "action", "result", "reflection"] as const;
const TYPE_NAME: Record<string, string> = {
  behavioral: "Behavioral",
  hiring_manager: "Hiring manager",
  technical_qa: "Technical Q&A",
  case: "Case",
  recruiter_screen: "Recruiter screen",
  custom: "Custom",
};
const GROUP_TITLE = { rehearsal: "Rehearsals", story: "Story completion", resume: "Resume gaps and issues" } as const;

const skillName = (c: string) => c.replace(/_/g, " ").replace(/^./, (x) => x.toUpperCase());
const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Mocked "today": the browser's local date. */
function todayOf(): Date {
  const now = new Date();
  return new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
}

export function weekStart(today: Date): Date {
  const day = today.getUTCDay(); // 0 Sunday
  const start = new Date(today);
  start.setUTCDate(today.getUTCDate() + (day === 0 ? 1 : 1 - day));
  return start;
}

function item(fields: Partial<PlanItem> & Pick<PlanItem, "key" | "kind" | "title" | "status">): PlanItem {
  return { sub: null, due: null, action_label: null, action_target: null, target_id: null, ...fields };
}

function groupsOf(items: PlanItem[]): PlanGroup[] {
  return (["rehearsal", "story", "resume"] as const).map((kind) => {
    const of = items.filter((i) => i.kind === kind);
    const done = of.filter((i) => i.status === "done").length;
    const next = of.find((i) => i.status !== "done");
    const status = !of.length
      ? kind === "rehearsal"
        ? "Added when you add a target role"
        : "Nothing to do here yet"
      : !next
        ? "All done"
        : `Next: ${next.title}${next.sub ? `, ${next.sub}` : ""} · ${of.length - done} open`;
    return { kind, title: GROUP_TITLE[kind], done, total: of.length, status };
  });
}

async function get<T>(origin: string, path: string): Promise<T | null> {
  const resp = await fetch(`${origin}/api${path}`);
  return resp.ok ? ((await resp.json()) as T) : null;
}

export function personalPlanHandlers() {
  return [
    http.get(`${API}/me/plan`, async ({ request }) => {
      const origin = new URL(request.url).origin;
      const [rehearsals, stories, resumes, profile] = await Promise.all([
        get<Rehearsals>(origin, "/rehearsals"),
        get<Story[]>(origin, "/stories"),
        get<ResumeOut[]>(origin, "/resumes"),
        get<Profile>(origin, "/account/profile"),
      ]);
      const style = profile?.plan_style ?? "weekly";
      const items: PlanItem[] = [];
      const steps: Record<string, { why: string | null; role_label: string | null; role_target: string | null }> = {};
      const rehearsalItems = [...(rehearsals?.items ?? [])].sort(
        (a, b) =>
          (a.role.interview_date ?? "9999").localeCompare(b.role.interview_date ?? "9999") ||
          (a.readiness.score ?? -1) - (b.readiness.score ?? -1),
      );
      for (const r of rehearsalItems) {
        const company = r.role.company_name ?? r.role.name ?? "Your role";
        const score = r.readiness.score;
        const key = `interview:${r.interview.id}`;
        items.push(
          item({
            key,
            kind: "rehearsal",
            title: `${company} · ${TYPE_NAME[r.interview.interview_type]}: readiness 75 or more`,
            sub: score === null ? "Not started" : `Now ${score}`,
            status: score !== null && score >= GOAL ? "done" : "todo",
            action_label: score === null ? "Start the take" : "Retake",
            action_target: `/interviews/${r.interview.id}`,
            target_id: r.interview.id,
          }),
        );
        const weakest = r.readiness.competencies.filter((c) => c.score !== null).sort((a, b) => (a.score ?? 0) - (b.score ?? 0))[0];
        steps[key] = {
          why: weakest ? `Your weakest skill there is ${skillName(weakest.competency).toLowerCase()}.` : null,
          role_label: `Open ${company}`,
          role_target: `/roles/${r.role.id}`,
        };
      }
      const library = stories ?? [];
      const tested = rehearsalItems.some((r) => ["behavioral", "hiring_manager"].includes(r.interview.interview_type));
      const covered = new Set<string>();
      for (const c of tested ? STORY_SKILLS : []) {
        const showing = library.filter((s) => (s.skills as string[]).includes(c));
        const ready = showing.find((s) => s.display_status !== "draft");
        const draft = showing.find((s) => s.display_status === "draft");
        const filled = draft ? PARTS.filter((p) => (draft[p] ?? "").trim()).length : 0;
        if (draft) covered.add(draft.id);
        items.push(
          item({
            key: `skill:${c}`,
            kind: "story",
            title: `${skillName(c)}: a ${ready?.display_status === "proven" ? "Proven" : "Ready"} story`,
            sub: ready ? ready.title : draft ? `“${draft.title}” has ${filled} of 5 parts` : "No story yet",
            status: ready ? "done" : "todo",
            action_label: ready ? null : draft ? "Open" : "Craft with Strova",
            action_target: ready ? `/stories/${ready.id}` : draft ? `/stories/${draft.id}/review` : `/coach/new?skill=${c}`,
          }),
        );
      }
      for (const s of library) {
        const filled = PARTS.filter((p) => (s[p] ?? "").trim()).length;
        if (s.display_status !== "draft" || covered.has(s.id) || filled === 0) continue;
        items.push(
          item({
            key: `story:${s.id}`,
            kind: "story",
            title: `Get “${s.title}” to Ready`,
            sub: `${filled} of 5 parts written`,
            status: "todo",
            action_label: "Open",
            action_target: `/stories/${s.id}/review`,
            target_id: s.id,
          }),
        );
      }
      const live = (resumes ?? []).filter((r) => !r.deleted);
      const main = live.find((r) => r.is_main) ?? live[0];
      if (main) {
        const [ideas, issues] = await Promise.all([
          get<StoryIdeasOut>(origin, `/resumes/${main.id}/story-ideas`),
          get<ResumeIssues>(origin, `/resumes/${main.id}/issues`),
        ]);
        for (const idea of (ideas?.ideas ?? []).slice(0, 2)) {
          items.push(
            item({
              key: `idea:${main.id}:${idea.resume_line_ref}`,
              kind: "story",
              title: `Build a story from “${idea.achievement}”`,
              sub: "A story idea from your resume",
              status: "todo",
              action_label: "Build on it",
              action_target: `/coach/new?resume=${main.id}&idea=${idea.resume_line_ref}`,
            }),
          );
        }
        for (const issue of issues?.accepted ?? [])
          items.push(item({ key: `issue:${issue.key}`, kind: "resume", title: issue.title, status: "done" }));
        for (const issue of issues?.open ?? [])
          items.push(
            item({
              key: `issue:${issue.key}`,
              kind: "resume",
              title: issue.title,
              sub: issue.detail,
              status: "todo",
              action_label: "Fix",
              action_target: `/resumes/${main.id}`,
            }),
          );
      }
      const ordered = [
        ...items.filter((i) => i.kind === "rehearsal"),
        ...items.filter((i) => i.kind === "story"),
        ...items.filter((i) => i.kind === "resume"),
      ];
      const next = ordered.find((i) => i.status !== "done") ?? null;
      if (next) next.status = "next";
      const today = todayOf();
      let shown = ordered;
      let start: string | null = null;
      let end: string | null = null;
      if (style === "weekly") {
        const monday = weekStart(today);
        const days = Array.from({ length: 6 }, (_, n) => {
          const d = new Date(monday);
          d.setUTCDate(monday.getUTCDate() + n);
          return iso(d);
        });
        const past = days.filter((d) => d < iso(today));
        const ahead = days.filter((d) => d >= iso(today));
        const done = ordered.filter((i) => i.status === "done");
        const doneShown = past.length ? done.slice(-past.length) : [];
        const open = ordered.filter((i) => i.status !== "done").slice(0, ahead.length);
        shown = [
          ...doneShown.map((i, n) => ({ ...i, due: past[past.length - doneShown.length + n] })),
          ...open.map((i, n) => ({ ...i, due: ahead[n] })),
        ];
        start = days[0];
        end = days[5];
      }
      const step = next
        ? {
            headline:
              next.kind === "rehearsal"
                ? `Rehearse ${next.title.split(":")[0]}${next.sub?.startsWith("Now") ? `: readiness ${next.sub.slice(4)} of 75` : ""}.`
                : next.kind === "story"
                  ? `${next.title.startsWith("Get") || next.title.startsWith("Build") ? next.title : `Get ${next.title[0].toLowerCase()}${next.title.slice(1)}`}.`
                  : `Fix your resume: ${next.title[0].toLowerCase()}${next.title.slice(1)}.`,
            why: steps[next.key]?.why ?? null,
            action_label: next.action_label ?? "Open",
            action_target: next.action_target ?? "/",
            role_label: steps[next.key]?.role_label ?? null,
            role_target: steps[next.key]?.role_target ?? null,
          }
        : null;
      const body: PersonalPlan = {
        plan: { style, week_start: start, items: shown },
        today: iso(today),
        week_end: end,
        groups: groupsOf(ordered),
        next_key: next?.key ?? null,
        next_step: step,
        has_roles: (rehearsals?.items.length ?? 0) > 0,
      };
      return HttpResponse.json(body);
    }),
  ];
}
