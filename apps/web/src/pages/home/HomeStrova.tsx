/**
 * HO-1 (mockup #home): Home with Strova. The greeting by time of day; Strova's next step (the
 * plan's next item, with the why line, its action and a link to its role); the four summary cards
 * (resumes, target roles, rehearsals, Career Stories); and the plan in the chosen style (weekly,
 * PS-4, or the checklist, PS-3). No suggestion lists here: they live where they act.
 */
import "../../components/ux/ux.css";
import "./home.css";

import type { ReactNode } from "react";
import { Link } from "react-router";

import { useAuth, useResumeIssues, useResumes, useStoryIdeas } from "../../api/hooks";
import { usePersonalPlan } from "../../api/personalPlan";
import { useRehearsals, useRoles } from "../../api/roles";
import { useSuggestions } from "../../api/suggestions";
import type { PersonalPlan, PlanGroup, PlanItem } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import { displayStatusLabel, useStories, type DisplayStatus } from "../stories/api";

type Kind = PlanItem["kind"];

export const KIND_CHIP: Record<Kind, { cls: string; label: string; legend: string }> = {
  rehearsal: { cls: "t", label: "Rehearsal", legend: "mock interviews" },
  story: { cls: "v", label: "Story", legend: "story goals" },
  resume: { cls: "warn", label: "Resume", legend: "Resume issues" },
};

/** HO-1: "Good morning" before noon, "Good afternoon" before 6 pm, else "Good evening". */
export function greeting(now: Date): string {
  const h = now.getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

const DAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const parseDay = (iso: string) => new Date(`${iso}T12:00:00`);
const monthDay = (iso: string) => parseDay(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

export function HomeStrova({ now = new Date() }: { now?: Date }) {
  const auth = useAuth();
  const plan = usePersonalPlan();
  const first = auth.data?.user?.full_name?.trim().split(/\s+/)[0];
  return (
    <div className="sx-page sx-page--wide home-strova">
      <h1>
        {greeting(now)}
        {first ? `, ${first}` : ""}
      </h1>
      {plan.isPending && <Loading label="Loading your plan" />}
      {plan.isError && <ErrorNotice error={plan.error} />}
      {plan.data && <NextStep plan={plan.data} />}
      <SummaryCards />
      {plan.data &&
        (plan.data.plan.style === "checklist" ? <Checklist plan={plan.data} /> : <Weekly plan={plan.data} />)}
    </div>
  );
}

/** HO-1: one sentence that introduces Strova beside her avatar. */
export const STROVA_INTRO =
  "Meet Strova, your interview partner: she reads your resume, helps you build the stories you'll tell, and rehearses the real interview with you.";

/**
 * HO-1: Strova's next step. Compact: the intro beside her avatar, then the step, its headline
 * clamped to two lines and the why line to one (the full text stays in the tooltip).
 */
function NextStep({ plan }: { plan: PersonalPlan }) {
  const step = plan.next_step;
  return (
    <section className="sx-hero home-strova__hero" aria-label="Strova's next step">
      <div className="home-strova__intro">
        <Strova mode="coaching" size={64} />
        <p className="sub">{STROVA_INTRO}</p>
      </div>
      <div className="home-strova__step">
        <div className="home-strova__step-text">
          <span className="sx-eyebrow home-strova__eyebrow">Strova · next step</span>
          {step ? (
            <>
              <div className="home-strova__headline" title={step.headline}>
                {step.headline}
              </div>
              {step.why && (
                <div className="sub home-strova__why" title={step.why}>
                  {step.why}
                </div>
              )}
            </>
          ) : (
            <div className="home-strova__headline">Your plan is clear. Add a target role, and Strova plans your rehearsals.</div>
          )}
        </div>
        <div className="sx-row home-strova__step-actions">
          {step ? (
            <>
              <Link className="sx-btn" to={step.action_target}>
                {step.action_label}
              </Link>
              {step.role_target && step.role_label && (
                <Link className="sx-btn ghost" to={step.role_target}>
                  {step.role_label}
                </Link>
              )}
            </>
          ) : (
            <Link className="sx-btn" to="/roles/new">
              Add a target role
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}

function KindChip({ kind }: { kind: Kind }) {
  return <span className={`sx-chip ${KIND_CHIP[kind].cls}`}>{KIND_CHIP[kind].label}</span>;
}

function PlanHead({ title, right }: { title: string; right: ReactNode }) {
  return (
    <div className="sx-between">
      <div className="sx-row">
        <Strova mode="coaching" size={28} />
        <h2 id="home-plan-heading">{title}</h2>
      </div>
      <span className="sx-small sx-muted">
        {right} · <Link to="/account/profile">Change style</Link>
      </span>
    </div>
  );
}

/** PS-4: this week, Monday to Saturday, one item a day; today's item highlighted. */
function Weekly({ plan }: { plan: PersonalPlan }) {
  const start = plan.plan.week_start;
  const end = plan.week_end;
  const items = [...plan.plan.items].sort((a, b) => (a.due ?? "").localeCompare(b.due ?? ""));
  return (
    <section className="sx-card coach" aria-labelledby="home-plan-heading" data-testid="weekly-plan">
      <PlanHead title="This week's plan" right={start && end ? `${monthDay(start)} to ${monthDay(end)}` : ""} />
      <div className="sx-chips sx-small" aria-label="Legend">
        {(["rehearsal", "story", "resume"] as Kind[]).map((k) => (
          <span key={k} className="sx-row home-strova__legend">
            <KindChip kind={k} />
            <span className="sx-muted">{KIND_CHIP[k].legend}</span>
          </span>
        ))}
      </div>
      {items.length === 0 ? (
        <p className="sx-small sx-muted">Nothing planned this week. Strova adds items as your stories, resume and roles change.</p>
      ) : (
        <ol className="plain-list" aria-label="This week">
          {items.map((i) => {
            const today = i.due === plan.today;
            const day = i.due ? (today ? "Today" : DAY[parseDay(i.due).getDay()]) : "";
            return <PlanRow key={i.key} item={i} day={day} highlight={today && i.status !== "done"} />;
          })}
        </ol>
      )}
    </section>
  );
}

function PlanRow({ item, day, highlight }: { item: PlanItem; day?: string; highlight: boolean }) {
  const done = item.status === "done";
  return (
    <li
      className={`home-planitem${highlight ? " next" : ""}`}
      data-testid="plan-item"
      data-status={item.status}
      aria-current={highlight ? "step" : undefined}
    >
      {day !== undefined && <span className="home-planitem__day">{day}</span>}
      <span className={`home-check${done ? " done" : ""}`} role="img" aria-label={done ? "Done" : "To do"} />
      <div className="sx-stack home-planitem__body">
        {done ? (
          <span className="sx-muted home-planitem__done">{item.title}</span>
        ) : highlight ? (
          <strong>{item.title}</strong>
        ) : (
          <span>{item.title}</span>
        )}
        {item.sub && !done && <span className="sx-small sx-muted">{item.sub}</span>}
        {day !== undefined && <KindChip kind={item.kind} />}
      </div>
      {!done && item.action_target && (
        <Link className={`sx-btn sm${highlight ? "" : " ghost"}`} to={item.action_target}>
          {highlight ? (item.action_label ?? "Open") : "Open"}
        </Link>
      )}
    </li>
  );
}

/** PS-3: three groups, collapsed by default, each with its count, progress and next item. */
function Checklist({ plan }: { plan: PersonalPlan }) {
  const done = plan.groups.reduce((n, g) => n + g.done, 0);
  const total = plan.groups.reduce((n, g) => n + g.total, 0);
  return (
    <section className="sx-card coach" aria-labelledby="home-plan-heading" data-testid="checklist-plan">
      <PlanHead title="Your readiness checklist" right={`${done} of ${total} done`} />
      {plan.groups.map((g) => (
        <CheckGroup key={g.kind} group={g} items={plan.plan.items.filter((i) => i.kind === g.kind)} nextKey={plan.next_key} />
      ))}
    </section>
  );
}

function CheckGroup({ group, items, nextKey }: { group: PlanGroup; items: PlanItem[]; nextKey: string | null }) {
  const pct = group.total ? Math.round((group.done / group.total) * 100) : 0;
  return (
    <details className="home-cgroup" data-kind={group.kind} data-testid={`group-${group.kind}`}>
      <summary>
        <div className="sx-between">
          <div className="sx-row">
            <KindChip kind={group.kind} />
            <h3>{group.title}</h3>
          </div>
          <div className="sx-row">
            <span className="sx-small sx-mono">
              {group.done} of {group.total} done
            </span>
            <span className="caret" aria-hidden="true">
              ▾
            </span>
          </div>
        </div>
        <div
          className={`sx-bar home-cgroup__bar ${group.kind === "story" ? "v" : ""}`}
          role="progressbar"
          aria-label={`${group.title} progress`}
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <span style={{ width: `${pct}%` }} />
        </div>
        <div className="sx-small sx-muted">{group.status}</div>
      </summary>
      <ol className="plain-list">
        {items.map((i) => (
          <PlanRow key={i.key} item={i} highlight={i.key === nextKey} />
        ))}
      </ol>
    </details>
  );
}

const plural = (n: number, word: string, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;

/** HO-1: the four summary cards, each opening its page. */
function SummaryCards() {
  const auth = useAuth();
  const resumes = useResumes();
  const live = (resumes.data ?? []).filter((r) => !r.deleted);
  const main = live.find((r) => r.is_main) ?? live[0] ?? null;
  const issues = useResumeIssues(main?.id ?? null);
  const ideas = useStoryIdeas(main?.id ?? null);
  const roles = useRoles();
  const rehearsals = useRehearsals();
  const stories = useStories();
  const suggestions = useSuggestions("stories");
  const first = auth.data?.user?.full_name?.trim().split(/\s+/)[0];
  const items = rehearsals.data?.items ?? [];
  const scored = items.filter((i) => i.readiness.score !== null);
  const best = scored.sort((a, b) => (b.readiness.score ?? 0) - (a.readiness.score ?? 0))[0];
  const counts = (["proven", "ready", "draft"] as DisplayStatus[])
    .map((s) => [s, (stories.data ?? []).filter((x) => x.display_status === s).length] as const)
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${n} ${displayStatusLabel[s]}`)
    .join(" · ");
  return (
    <div className="home-strova__cards" aria-label="Summary" role="region">
      <Link className="sx-card tight home-strova__card" to={main ? `/resumes/${main.id}` : "/resumes"}>
        <div className="sx-eyebrow plain">{first ? `${first}'s Resumes` : "Your resumes"}</div>
        {main ? (
          <>
            <h3 className="home-strova__name">
              <span className="home-strova__truncate" title={main.name ?? undefined}>
                {main.name}
              </span>
              {main.is_main && <span className="sx-chip dark">Main</span>}
            </h3>
            <span className="sx-small home-strova__warn">{plural(issues.data?.open.length ?? 0, "issue")} open</span>
            <span className="sx-small home-strova__violet">{plural(ideas.data?.ideas.length ?? 0, "story idea")}</span>
          </>
        ) : (
          <h3>Add your resume</h3>
        )}
      </Link>
      <Link className="sx-card tight home-strova__card" to="/roles" data-testid="roles-card">
        <div className="sx-eyebrow teal">Target roles</div>
        <h3>{plural(roles.data?.length ?? 0, "role")}</h3>
        {(roles.data ?? []).slice(0, 2).map(({ role }) => (
          <span key={role.id} className="sx-small sx-muted">
            {role.company_name ?? role.name ?? "Role"} ·{" "}
            {role.days_left === null || role.days_left < 0
              ? "no date"
              : role.days_left === 0
                ? "today"
                : `${role.days_left} ${role.days_left === 1 ? "day" : "days"}`}
          </span>
        ))}
      </Link>
      <Link className="sx-card tight home-strova__card" to="/rehearsals">
        <div className="sx-eyebrow teal">Rehearsals with Strova</div>
        <h3>{plural(items.length, "interview")}</h3>
        {best && (
          <span className="sx-small sx-muted">
            Best: {best.role.company_name ?? best.role.name} · {best.readiness.score}
          </span>
        )}
        {items.length > 0 && (
          <span className="sx-small sx-muted">{items.length - scored.length} not started</span>
        )}
      </Link>
      <Link className="sx-card tight home-strova__card" to="/stories" data-testid="stories-card">
        <div className="sx-eyebrow">Career Stories with Strova</div>
        <h3>{plural(stories.data?.length ?? 0, "story", "stories")}</h3>
        {counts && <span className="sx-small home-strova__ok">{counts}</span>}
        <span className="sx-small home-strova__violet">
          {plural(suggestions.data?.length ?? 0, "suggestion")} from Strova
        </span>
      </Link>
    </div>
  );
}
