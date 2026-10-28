import type { AgentActivity } from "./voice";

/**
 * AV-1: the 3D avatar is off at build time unless VITE_INTERVIEWER_AVATAR is "on". Its
 * components and tests stay in ./avatar.
 */
export function avatarEnabled(): boolean {
  return import.meta.env.VITE_INTERVIEWER_AVATAR === "on";
}

const stateText: Record<AgentActivity, string> = {
  idle: "Interviewer is joining",
  listening: "Interviewer is listening",
  thinking: "Interviewer is thinking",
  speaking: "Interviewer is speaking",
};

/**
 * AV-1: what the interviewer is doing, without the avatar: rings that light up by state, and the
 * state in words. The rings are decoration; the words carry the state.
 */
export function InterviewerState({ activity }: { activity: AgentActivity }) {
  return (
    <div className="interviewer-state" data-activity={activity} data-testid="interviewer-state">
      <svg className="interviewer-state__orb" width="160" height="160" viewBox="0 0 160 160" aria-hidden="true">
        <circle className="interviewer-state__outer" cx="80" cy="80" r="76" />
        <circle className="interviewer-state__middle" cx="80" cy="80" r="58" />
        <circle className="interviewer-state__inner" cx="80" cy="80" r="40" />
        <circle className="interviewer-state__core" cx="80" cy="80" r="14" />
      </svg>
      <p className="interviewer-state__text">{stateText[activity]}</p>
    </div>
  );
}
