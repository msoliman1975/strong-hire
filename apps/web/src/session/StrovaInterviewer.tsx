/**
 * SV-6 (mockup #live): Strova at 160 px in the interviewer hat. Her mode follows the real
 * interviewer state (listening while the candidate speaks, thinking while the turn is computed,
 * speaking while the voice plays), with the state in words in a chip, and the line "Strova is
 * acting as {title} at {company}" from the interview (U06).
 */
import { useRoleInterviews } from "../api/roles";
import type { SessionRecord } from "../api/types";
import { Strova, type StrovaMode } from "../components/strova";
import type { AgentActivity } from "./voice";

const MODE: Record<AgentActivity, StrovaMode> = {
  idle: "interviewing",
  listening: "listening",
  thinking: "thinking",
  speaking: "speaking",
};

const CHIP: Record<AgentActivity, string> = {
  idle: "Strova is joining",
  listening: "Strova is listening",
  thinking: "Strova is thinking",
  speaking: "Strova is speaking",
};

/** "Strova is acting as Hiring Manager at Stripe", from the session's interview. */
export function useActingAs(session: SessionRecord): string | null {
  const interviews = useRoleInterviews(session.job_target_id);
  const match = interviews.data?.find(
    (i) =>
      i.interview.interview_type === session.config.interview_type &&
      (!session.resume_id || i.interview.resume_id === session.resume_id),
  );
  return match?.interview.acting_as.text ?? null;
}

export function StrovaInterviewer({ activity, session }: { activity: AgentActivity; session: SessionRecord }) {
  const acting = useActingAs(session);
  return (
    <div className="strova-room" data-testid="interviewer-state" data-activity={activity}>
      <Strova mode={MODE[activity]} size={160} hat="interviewer" />
      <div className="strova-room__name">Strova</div>
      {acting && <div className="strova-room__acting">{acting.replace("acting as ", "acting as\n")}</div>}
      <span className="strova-room__chip" role="status">
        {CHIP[activity]}
      </span>
    </div>
  );
}
