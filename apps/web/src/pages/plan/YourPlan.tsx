/**
 * PP-1, PP-4, RD-2: "Your plan", one card for what used to be "Your next steps" (the day plan) and
 * "Next rehearsal" (the setup). It lists the steps in order:
 *
 * - done: the rehearsals already debriefed, ticked, each linking to its debrief;
 * - to do: the day plan's steps (RD-2: by day until the interview date, else the next steps).
 *
 * The first step not done is open. A rehearsal step opens with the setup inline (PlanSetup: every
 * PP-4 option, CU-9 and CU-10 prefills) and "Start rehearsal"; a story step opens with the coach.
 * Other steps are one line each, and any of them can be opened instead.
 */
import { useState } from "react";
import { Link } from "react-router";

import { reportPath } from "../../api/reports";
import type { ReportItem } from "../../api/types";
import { ErrorNotice, Loading } from "../../components/ui";
import { competencyLabel, difficultyLabel, formatDate, interviewTypeLabel, modeLabelV2 as modeLabel } from "../../labels";
import { newCoachPath } from "../coach/paths";
import type { PlanView } from "./api";
import { PlanSetup, type SuggestedRehearsal } from "./PlanSetup";
import { useDayPlan, type DayPlanItem } from "./ReadinessApi";
import { GAP_COPY } from "../../copy";

/** One step still to do: a day plan item, with its day when the plan runs by day. */
interface TodoStep {
  key: string;
  day: string | null;
  item: DayPlanItem | null; // null: the setup alone, when the day plan has no rehearsal
}

export function stepTitle(item: DayPlanItem | null): string {
  if (!item) return "Your next rehearsal";
  if (item.kind === "story") {
    const skill = item.competency ? competencyLabel(item.competency) : "a tested skill";
    return item.strength === "missing" ? `Build a story for ${skill}` : `Strengthen your story for ${skill}`;
  }
  const type = item.interview_type ? interviewTypeLabel[item.interview_type] : "Rehearsal";
  const parts = [item.difficulty && difficultyLabel[item.difficulty], item.mode && `${modeLabel[item.mode]} mode`].filter(Boolean);
  return `${type} rehearsal${parts.length ? `: ${parts.join(", ")}` : ""}`;
}

function doneTitle(r: ReportItem): string {
  const type = r.interview_type ? `${interviewTypeLabel[r.interview_type]} rehearsal` : "Rehearsal";
  return r.hire_signal ? `${type}: ${r.hire_signal}` : type;
}

export function YourPlan({ plan, jobId, resumeId }: { plan: PlanView; jobId: string; resumeId: string }) {
  const dayPlan = useDayPlan(jobId, resumeId);
  const done = plan.reports
    .filter((r) => r.type === "interview_debrief" && r.status === "ready")
    .sort((a, b) => a.at.localeCompare(b.at));

  const todo: TodoStep[] = [];
  if (dayPlan.data?.kind === "by_day") {
    for (const d of dayPlan.data.days) {
      d.items.forEach((item, i) => todo.push({ key: `${d.day}-${i}`, day: d.day, item }));
    }
  } else if (dayPlan.data) {
    dayPlan.data.next_steps.forEach((item, i) => todo.push({ key: `next-${i}`, day: null, item }));
  }
  // There is always a rehearsal to start: with none in the day plan, the setup is its own step.
  if (!dayPlan.isPending && !todo.some((t) => t.item?.kind === "rehearsal")) {
    todo.push({ key: "setup", day: null, item: null });
  }

  const [openKey, setOpenKey] = useState<string | null>(null);
  const open = openKey ?? todo[0]?.key ?? null;

  return (
    <section className="card plan-next your-plan" aria-labelledby="your-plan-heading" data-testid="your-plan">
      <h2 id="your-plan-heading">Your plan</h2>
      <p className="muted">
        {dayPlan.data?.kind === "by_day"
          ? "Day by day until your interview. Start the open step, or open another one."
          : "Your next steps, in order. Add your interview date to get a plan for each day."}
      </p>
      {dayPlan.isError && <ErrorNotice error={dayPlan.error} />}
      <ol className="plain-list your-plan__steps">
        {done.map((r) => (
          <li key={r.id} className="your-plan__step" data-state="done" data-testid="plan-step">
            <span className="your-plan__mark" aria-hidden="true">
              ✓
            </span>
            <div className="your-plan__line">
              <span>
                {doneTitle(r)} <span className="visually-hidden">(done)</span>
              </span>
              <span className="your-plan__meta">
                {formatDate(r.at)} · <Link to={reportPath(r)}>Debrief</Link>
              </span>
            </div>
          </li>
        ))}
        {dayPlan.isPending && (
          <li>
            <Loading label="Loading your plan" />
          </li>
        )}
        {todo.map((t, i) => {
          const isOpen = t.key === open;
          return (
            <li key={t.key} className="your-plan__step" data-state={isOpen ? "open" : "todo"} data-testid="plan-step">
              <span className="your-plan__mark" aria-hidden="true">
                {done.length + i + 1}
              </span>
              <div className="your-plan__body">
                <div className="your-plan__line">
                  <span>
                    {t.day && <span className="your-plan__day">{formatDate(t.day)} · </span>}
                    <b>{stepTitle(t.item)}</b>
                  </span>
                  {!isOpen && (
                    <button
                      type="button"
                      className="text-button"
                      aria-expanded={false}
                      onClick={() => setOpenKey(t.key)}
                    >
                      Open
                    </button>
                  )}
                </div>
                {isOpen && <OpenStep step={t} first={i === 0} plan={plan} jobId={jobId} resumeId={resumeId} />}
              </div>
            </li>
          );
        })}
      </ol>
      {dayPlan.data?.kind === "by_day" && dayPlan.data.days_not_shown > 0 && (
        <p className="muted small">
          {dayPlan.data.days_not_shown} more {dayPlan.data.days_not_shown === 1 ? "day" : "days"} after these. The plan
          fills them in as the interview gets closer.
        </p>
      )}
    </section>
  );
}

function OpenStep({
  step,
  first,
  plan,
  jobId,
  resumeId,
}: {
  step: TodoStep;
  /** The first step uses the plan's own recommended setup (PR-2, GA-3); a later one, its own. */
  first: boolean;
  plan: PlanView;
  jobId: string;
  resumeId: string;
}) {
  const item = step.item;
  if (item?.kind === "story") {
    return (
      <div className="your-plan__open stack">
        <p className="muted">{item.reason}</p>
        <div>
          <Link
            className="btn"
            to={newCoachPath({ skill: item.competency ?? undefined, story: item.story_id ?? undefined, job: jobId })}
          >
            {item.strength === "missing" ? "Build it with the coach" : "Work on it with the coach"}
          </Link>
        </div>
      </div>
    );
  }
  const suggested: SuggestedRehearsal | null =
    item && !first
      ? { interview_type: item.interview_type, difficulty: item.difficulty, mode: item.mode }
      : null;
  return (
    <div className="your-plan__open stack">
      <p className="muted">
        {item
          ? `${item.focus_topics.length ? `${item.focus_topics.join(", ")}. ` : ""}${item.reason} Change anything.`
          : plan.next_session
            ? `${GAP_COPY.setUpFrom} ${plan.next_session.reason} Change anything.`
            : "Set up from your plan. Change anything."}
      </p>
      {/* The key resets the setup when another step opens, so it starts from that step. */}
      <PlanSetup key={step.key} plan={plan} jobId={jobId} resumeId={resumeId} embedded suggested={suggested} />
    </div>
  );
}
