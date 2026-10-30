/**
 * RD-2: what to do each day until the interview date, or the next three steps without one.
 * The API rebuilds it from the latest debrief, gap analysis and story fit on every read.
 */
import { ErrorNotice, Loading, Tag } from "../../components/ui";
import { competencyLabel, difficultyLabel, formatDate, interviewTypeLabel, modeLabelV2 as modeLabel } from "../../labels";
import { useDayPlan, type DayPlanItem } from "./ReadinessApi";
import "./Readiness.css";

function Item({ item }: { item: DayPlanItem }) {
  if (item.kind === "story") {
    return (
      <li className="day-plan__item" data-testid="day-plan-item" data-kind="story">
        <strong>
          {item.strength === "missing" ? "Build a story" : "Strengthen your story"} for{" "}
          {item.competency ? competencyLabel(item.competency) : "a tested skill"}
        </strong>
        <span className="muted small"> {item.reason}</span>
      </li>
    );
  }
  return (
    <li className="day-plan__item" data-testid="day-plan-item" data-kind="rehearsal">
      <strong>{item.interview_type ? interviewTypeLabel[item.interview_type] : "Rehearsal"} rehearsal</strong>{" "}
      {item.difficulty && <Tag>{difficultyLabel[item.difficulty]}</Tag>} {item.mode && <Tag>{modeLabel[item.mode]}</Tag>}
      {item.focus_topics.length > 0 && <span className="muted small"> {item.focus_topics.join(", ")}.</span>}
      <span className="muted small"> {item.reason}</span>
    </li>
  );
}

export function DayPlan({ jobId, resumeId }: { jobId: string; resumeId: string }) {
  const plan = useDayPlan(jobId, resumeId);
  return (
    <section className="card" aria-labelledby="plan-days-heading" data-testid="day-plan">
      <h2 id="plan-days-heading">{plan.data?.kind === "by_day" ? "Your plan, day by day" : "Your next steps"}</h2>
      {plan.isPending ? (
        <Loading label="Loading your day plan" />
      ) : plan.isError ? (
        <ErrorNotice error={plan.error} />
      ) : plan.data.kind === "next_steps" ? (
        <>
          <p className="muted">Add your interview date to get a plan for each day until then.</p>
          <ol className="plain-list day-plan__items">
            {plan.data.next_steps.map((item, i) => (
              <Item key={i} item={item} />
            ))}
          </ol>
        </>
      ) : (
        <>
          <ol className="plain-list day-plan__days">
            {plan.data.days.map((d) => (
              <li key={d.day} className="day-plan__day" data-testid="day-plan-day">
                <h3>{formatDate(d.day)}</h3>
                <ul className="plain-list day-plan__items">
                  {d.items.map((item, i) => (
                    <Item key={i} item={item} />
                  ))}
                </ul>
              </li>
            ))}
          </ol>
          {plan.data.days_not_shown > 0 && (
            <p className="muted small">
              {plan.data.days_not_shown} more {plan.data.days_not_shown === 1 ? "day" : "days"} after these. The plan
              fills them in as the interview gets closer.
            </p>
          )}
        </>
      )}
    </section>
  );
}
