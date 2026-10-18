import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { keys, useJob, useProfile, useUsage } from "../api/hooks";
import { sessionsApi } from "../api/sessions";
import { isPausedError, SESSIONS_UNAVAILABLE, statusKey, useSiteStatus } from "../api/status";
import type { Difficulty, InterviewType, Level, Mode, SessionConfig, SessionSetup } from "../api/types";
import { Choices } from "../components/Choices";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { CustomFields } from "../custom/CustomFields";
import type { CustomDuration } from "../custom/rules";
import { useCustomSetup } from "../custom/useCustomSetup";
import {
  difficultyHint,
  difficultyLabel,
  interviewTypeHint,
  interviewTypeLabel,
  levelLabel,
  modeHint,
  modeLabel,
} from "../labels";

// The four standard types, then Custom (D-1), which opens its own setup below the type choice.
const TYPES = Object.keys(interviewTypeLabel) as InterviewType[];
const DIFFICULTIES = Object.keys(difficultyLabel) as Difficulty[];
const MODES = Object.keys(modeLabel) as Mode[];
const LEVELS = Object.keys(levelLabel) as Level[];
type Duration = SessionConfig["duration_min"];
const DURATIONS: Duration[] = [10, 30, 45];
const MINI: Duration = 10;

/** The paywall reason for a locked Custom interview (CU-11). */
export const CUSTOM_LOCKED_REASON = "custom_requires_plan";

/** Router state that prefills the setup: "Run this setup again" (CU-9). */
export interface SetupState {
  setup?: SessionSetup;
}

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

/** Journey 2, step 1: type, difficulty, duration and mode. Custom adds its own setup (CU-1 to CU-5). */
export function SessionSetupPage() {
  const { jobId = "" } = useParams();
  const [params] = useSearchParams();
  const location = useLocation();
  // CU-9: an earlier session's setup, from "Run this setup again".
  const [prefill] = useState<SessionSetup | null>(() => (location.state as SetupState | null)?.setup ?? null);
  const job = useJob(jobId);
  const usage = useUsage();
  const profile = useProfile();
  const siteStatus = useSiteStatus();
  // PR-3: the CV chosen for this rehearsal. Without one, the API uses the job's latest gap analysis.
  const resumeId = params.get("resume") ?? prefill?.resume_id ?? null;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [type, setType] = useState<InterviewType>(
    prefill?.config.interview_type ?? pick(params.get("type"), TYPES, "behavioral"),
  );
  const [difficulty, setDifficulty] = useState<Difficulty>(
    prefill?.config.difficulty ?? pick(params.get("difficulty"), DIFFICULTIES, "realistic"),
  );
  const [duration, setDuration] = useState<Duration | null>(prefill ? prefill.config.duration_min : null);
  // Coach first: the controls (pause, hint, redo) help a new candidate; Realistic is one click away.
  const [mode, setMode] = useState<Mode>(prefill?.config.mode ?? pick(params.get("mode"), MODES, "coach"));
  const [level, setLevel] = useState<Level | "">(prefill?.config.level ?? "");

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
        prefill && prefill.config.duration_min !== MINI ? (prefill.config.duration_min as CustomDuration) : undefined,
      spec: prefill?.config.custom ?? null,
    },
  });

  const start = useMutation({
    mutationFn: (config: SessionConfig) =>
      sessionsApi.create({ job_target_id: jobId, resume_id: resumeId, config, channel: "voice" }),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: keys.usage });
      navigate(`/sessions/${session.id}/live`);
    },
    onError: (err) => {
      if (isPausedError(err)) void queryClient.invalidateQueries({ queryKey: statusKey });
      if (err instanceof ApiError && err.status === 402) {
        void queryClient.invalidateQueries({ queryKey: keys.usage });
        navigate(`/upgrade?reason=${encodeURIComponent(err.code ?? "upgrade_required")}`);
      }
      // CU-11: Custom was switched to paid plans only after the page loaded.
      if (err instanceof ApiError && err.status === 403 && err.code === "upgrade_required") {
        void queryClient.invalidateQueries({ queryKey: statusKey });
        navigate(`/upgrade?reason=${CUSTOM_LOCKED_REASON}`);
      }
    },
  });

  if (job.isPending) return <Loading />;
  if (job.isError) return <ErrorNotice error={job.error} />;

  // AC-3: the profile's target level is the default when the posting gives no level.
  const chosenLevel: Level | "" = level || job.data.level || profile.data?.target_level || "";
  const posting = job.data.posting;
  const chosenDuration: Duration = fullAllowed ? (duration ?? 30) : MINI;
  const sessionsClosed = siteStatus.data?.voice_sessions_open === false;
  const blocked = type === "custom" && (customLocked || custom.problems.length > 0);
  const redirected =
    start.error instanceof ApiError &&
    (start.error.status === 402 || (start.error.status === 403 && start.error.code === "upgrade_required"));

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!chosenLevel || blocked) return;
    start.mutate({
      interview_type: type,
      difficulty,
      mode,
      duration_min: isCustom ? custom.duration : chosenDuration,
      level: chosenLevel,
      custom: isCustom ? custom.spec() : null,
    });
  };

  return (
    <div className="page--narrow">
      <PageHead title="Set up your interview">
        {posting && (
          <p>
            {posting.title} at {posting.company_name}
          </p>
        )}
      </PageHead>
      <form className="panel" onSubmit={onSubmit} noValidate>
        <Choices
          legend="Interview type"
          name="type"
          options={TYPES}
          value={type}
          onChange={setType}
          label={(v) => interviewTypeLabel[v]}
          hint={(v) => (v === "custom" && customLocked ? "Part of the subscription." : interviewTypeHint[v])}
          disabled={(v) => v === "custom" && customLocked}
          describedBy={customLocked ? "custom-locked" : undefined}
        />
        {customLocked && (
          <p className="hint" id="custom-locked" data-testid="custom-locked">
            Custom interviews, where you mix question types and add your own questions, are part of the subscription.{" "}
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
              describedBy={fullAllowed ? undefined : "duration-hint"}
            />
            {!fullAllowed && (
              <p className="hint" id="duration-hint">
                Full interviews (30 and 45 minutes) need a subscription. Free accounts get{" "}
                {usage.data ? `${usage.data.free_interviews_total} ` : ""}mini interviews.{" "}
                <Link to="/upgrade">See the monthly plan</Link>
              </p>
            )}
          </>
        )}
        <div className="field">
          <label htmlFor="level">Level</label>
          <p className="hint" id="level-hint">
            The interviewer sets the bar for this level. We took it from the job posting.
          </p>
          <select
            id="level"
            value={chosenLevel}
            onChange={(e) => setLevel(e.target.value as Level)}
            aria-describedby="level-hint"
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
        <p className="muted">Before the interview starts, we check your microphone and connection.</p>
        {/* OC-2, OC-3: new sessions are paused, or the daily spend cap is reached. */}
        {(sessionsClosed || isPausedError(start.error)) && (
          <div className="notice" role="status" data-testid="sessions-unavailable">
            <p>{isPausedError(start.error) ? start.error.message : SESSIONS_UNAVAILABLE}</p>
          </div>
        )}
        {start.isError && !isPausedError(start.error) && !redirected && (
          <ErrorNotice error={start.error} title="The interview could not start" />
        )}
        <div className="row section">
          <button type="submit" className="btn" disabled={start.isPending || !chosenLevel || sessionsClosed || blocked}>
            Start interview
          </button>
        </div>
      </form>
    </div>
  );
}
