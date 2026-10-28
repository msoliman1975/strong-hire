/**
 * PP-4: the "Next rehearsal" setup on the plan page. It keeps every v1 option of the session
 * setup page: type (Custom included, with the shared Custom components), difficulty, tone (TN-1),
 * mode, duration and level. Starting calls the same POST /sessions.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { keys, useProfile, useUsage } from "../../api/hooks";
import { CUSTOM_LOCKED_REASON, paywallReason, sessionsApi } from "../../api/sessions";
import { isPausedError, SESSIONS_UNAVAILABLE, statusKey, useSiteStatus } from "../../api/status";
import type {
  CustomRecommendation,
  Difficulty,
  InterviewType,
  Level,
  Mode,
  SessionConfig,
  SessionSetup,
} from "../../api/types";
import { Choices } from "../../components/Choices";
import { ErrorNotice } from "../../components/ui";
import { CustomFields } from "../../custom/CustomFields";
import type { SetupState } from "../../custom/repeat";
import type { CustomDuration } from "../../custom/rules";
import { useCustomSetup } from "../../custom/useCustomSetup";
import {
  difficultyHint,
  difficultyLabel,
  interviewTypeHint,
  interviewTypeLabel,
  levelLabel,
  modeHint,
  modeLabel,
} from "../../labels";
import type { PlanView, Tone } from "./api";

// The four standard types, then Custom (D-1). S35 adds Recruiter screen (RS-1) to this list.
const TYPES: InterviewType[] = ["behavioral", "hiring_manager", "technical_qa", "case", "custom"];
const DIFFICULTIES = Object.keys(difficultyLabel) as Difficulty[];
const MODES = Object.keys(modeLabel) as Mode[];
const LEVELS = Object.keys(levelLabel) as Level[];
type Duration = SessionConfig["duration_min"];
const DURATIONS: Duration[] = [10, 30, 45];
const MINI: Duration = 10;

/** TN-1. In generic mode there is no company persona, so "like the company" is left out (TN-3). */
function toneOptions(company: string | null, generic: boolean): Tone[] {
  return generic || !company ? ["warm", "neutral", "direct"] : ["as_company", "warm", "neutral", "direct"];
}

function toneLabel(tone: Tone, company: string | null): string {
  if (tone === "as_company") return `Like ${company ?? "the company"}`;
  return { warm: "Warm", neutral: "Neutral", direct: "Direct" }[tone];
}

const TONE_HINT: Record<Tone, string> = {
  as_company: "The tone of this company's interviewers, from its profile.",
  warm: "Friendly and encouraging. The questions stay as hard.",
  neutral: "Even and professional.",
  direct: "Brisk and to the point.",
};

function durationLabel(minutes: Duration): string {
  return minutes === MINI ? "10 minutes (mini)" : `${minutes} minutes`;
}

function durationHint(minutes: Duration, fullAllowed: boolean): string {
  if (minutes === MINI) return "3 questions, no candidate questions. A short practice round.";
  return fullAllowed ? "A full interview." : "Needs a subscription.";
}

function pick<T extends string>(value: string | null, options: T[], fallback: T): T {
  return options.includes(value as T) ? (value as T) : fallback;
}

export function PlanSetup({ plan, jobId, resumeId }: { plan: PlanView; jobId: string; resumeId: string }) {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  // CU-9 and CU-10 arrive as router state, as on the v1 setup page.
  const [prefill] = useState<SessionSetup | null>(() => (location.state as SetupState | null)?.setup ?? null);
  const [recommended] = useState<CustomRecommendation | null>(
    () => (prefill ? null : ((location.state as SetupState | null)?.recommended ?? null)),
  );
  const defaults = plan.setup;
  const usage = useUsage();
  const profile = useProfile();
  const siteStatus = useSiteStatus();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const generic = plan.company_mode === "generic";
  const tones = toneOptions(plan.company_name, generic);

  const [type, setType] = useState<InterviewType>(
    prefill?.config.interview_type ??
      (recommended ? "custom" : pick(params.get("type"), TYPES, pick(defaults.interview_type, TYPES, "behavioral"))),
  );
  const [difficulty, setDifficulty] = useState<Difficulty>(
    prefill?.config.difficulty ?? recommended?.difficulty ?? pick(params.get("difficulty"), DIFFICULTIES, defaults.difficulty),
  );
  const [tone, setTone] = useState<Tone>(pick(prefill?.config.tone ?? defaults.tone, tones, tones[0]));
  const [duration, setDuration] = useState<Duration | null>(prefill ? prefill.config.duration_min : null);
  const [mode, setMode] = useState<Mode>(prefill?.config.mode ?? pick(params.get("mode"), MODES, defaults.mode));
  const [level, setLevel] = useState<Level | "">(prefill?.config.level ?? "");
  const [refusedInline, setRefusedInline] = useState(false);

  // Free accounts get mini interviews only (BL-2). Until the usage is known, assume the free plan.
  const fullAllowed = usage.data?.full_interviews_allowed ?? false;
  // CU-11: under paid_only, Custom is locked for accounts without the plan.
  const customLocked = siteStatus.data?.custom_interview_access === "paid_only" && !fullAllowed;
  const isCustom = type === "custom" && !customLocked;
  const custom = useCustomSetup({
    jobId,
    resumeId,
    enabled: isCustom,
    longAllowed: fullAllowed,
    init: {
      duration:
        prefill && prefill.config.duration_min !== MINI
          ? (prefill.config.duration_min as CustomDuration)
          : recommended?.duration_min,
      spec: prefill?.config.custom ?? recommended?.custom ?? null,
    },
  });

  const start = useMutation({
    mutationFn: (config: SessionConfig) =>
      sessionsApi.create({ job_target_id: jobId, resume_id: resumeId, config, channel: "voice" }),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: keys.usage });
      navigate(`/sessions/${session.id}/live`);
    },
    onError: (err, config) => {
      if (isPausedError(err)) void queryClient.invalidateQueries({ queryKey: statusKey });
      if (config.interview_type === "custom" && custom.showRefusal(err, config.custom)) {
        setRefusedInline(true);
        return;
      }
      const reason = paywallReason(err, config.interview_type === "custom");
      if (reason) {
        void queryClient.invalidateQueries({ queryKey: reason === CUSTOM_LOCKED_REASON ? statusKey : keys.usage });
        navigate(`/upgrade?reason=${encodeURIComponent(reason)}`);
      }
    },
  });

  // AC-3: the job's level, else the profile's target level.
  const chosenLevel: Level | "" = level || defaults.level || profile.data?.target_level || "";
  const chosenDuration: Duration = fullAllowed ? (duration ?? defaults.duration_min) : MINI;
  const sessionsClosed = siteStatus.data?.voice_sessions_open === false;
  const blocked = type === "custom" && (customLocked || custom.problems.length > 0);
  const redirected = paywallReason(start.error, type === "custom") !== null;
  // A gap analysis of this pair is needed to build the interviewer brief (PR-3).
  const gapReady = plan.gap?.status === "ready";

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!chosenLevel || blocked || !gapReady) return;
    custom.clearRefusal();
    setRefusedInline(false);
    start.mutate({
      interview_type: type,
      difficulty,
      mode,
      duration_min: isCustom ? custom.duration : chosenDuration,
      level: chosenLevel,
      custom: isCustom ? custom.spec() : null,
      tone,
    });
  };

  return (
    <section className="card plan-next" aria-labelledby="plan-next-heading">
      <h2 id="plan-next-heading">Next rehearsal</h2>
      <p className="muted">
        {plan.next_session
          ? `Set up from your gaps: ${plan.next_session.reason} Change anything.`
          : "Set up from your plan. Change anything."}
      </p>
      <form onSubmit={onSubmit} noValidate className="stack">
        <Choices
          legend="Interview type"
          name="type"
          options={TYPES}
          value={type}
          onChange={setType}
          label={(v) => interviewTypeLabel[v]}
          hint={(v) => (v === "custom" && customLocked ? "Part of the subscription." : interviewTypeHint[v])}
          disabled={(v) => v === "custom" && customLocked}
          describedBy={customLocked ? "plan-custom-locked" : undefined}
        />
        {customLocked && (
          <p className="hint" id="plan-custom-locked" data-testid="custom-locked">
            Custom interviews are part of the subscription.{" "}
            <Link to={`/upgrade?reason=${CUSTOM_LOCKED_REASON}`}>Upgrade to build your own interview</Link>
          </p>
        )}
        {isCustom && <CustomFields setup={custom} longAllowed={fullAllowed} />}
        <Choices
          legend="Difficulty"
          name="difficulty"
          options={DIFFICULTIES}
          value={difficulty}
          onChange={setDifficulty}
          label={(v) => difficultyLabel[v]}
          hint={(v) => difficultyHint[v]}
        />
        <Choices
          legend="Interviewer tone"
          name="tone"
          options={tones}
          value={tone}
          onChange={setTone}
          label={(v) => toneLabel(v, plan.company_name)}
          hint={(v) => TONE_HINT[v]}
        />
        <Choices
          legend="Mode"
          name="mode"
          options={MODES}
          value={mode}
          onChange={setMode}
          label={(v) => modeLabel[v]}
          hint={(v) => modeHint[v]}
        />
        {!isCustom && (
          <>
            <Choices
              legend="Duration"
              name="duration"
              options={DURATIONS.map(String) as `${Duration}`[]}
              value={String(chosenDuration) as `${Duration}`}
              onChange={(v) => setDuration(Number(v) as Duration)}
              label={(v) => durationLabel(Number(v) as Duration)}
              hint={(v) => durationHint(Number(v) as Duration, fullAllowed)}
              disabled={(v) => !fullAllowed && Number(v) !== MINI}
              describedBy={fullAllowed ? undefined : "plan-duration-hint"}
            />
            {!fullAllowed && (
              <p className="hint" id="plan-duration-hint">
                Full interviews (30 and 45 minutes) need a subscription. Free accounts get{" "}
                {usage.data ? `${usage.data.free_interviews_total} ` : ""}mini interviews.{" "}
                <Link to="/upgrade">See the monthly plan</Link>
              </p>
            )}
          </>
        )}
        <div className="field">
          <label htmlFor="plan-level">Level</label>
          <select
            id="plan-level"
            value={chosenLevel}
            onChange={(e) => setLevel(e.target.value as Level)}
            aria-invalid={!chosenLevel ? true : undefined}
          >
            <option value="">Choose a level</option>
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {levelLabel[l]}
              </option>
            ))}
          </select>
          {!chosenLevel && <p className="field-error">Choose a level to start.</p>}
        </div>
        {!gapReady && (
          <p className="hint" data-testid="needs-gap">
            The rehearsal starts once the gap analysis for this job and CV is ready.
          </p>
        )}
        {(sessionsClosed || isPausedError(start.error)) && (
          <div className="notice" role="status" data-testid="sessions-unavailable">
            <p>{isPausedError(start.error) ? start.error.message : SESSIONS_UNAVAILABLE}</p>
          </div>
        )}
        {start.isError && !isPausedError(start.error) && !redirected && !refusedInline && (
          <ErrorNotice error={start.error} title="The interview could not start" />
        )}
        <button
          type="submit"
          className="btn btn--block"
          disabled={start.isPending || !chosenLevel || sessionsClosed || blocked || !gapReady}
        >
          Start rehearsal
        </button>
      </form>
    </section>
  );
}
