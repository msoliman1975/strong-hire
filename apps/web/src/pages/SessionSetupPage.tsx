import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { keys, useJob } from "../api/hooks";
import { sessionsApi } from "../api/sessions";
import type { Difficulty, InterviewType, Level, Mode, SessionConfig } from "../api/types";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import {
  difficultyHint,
  difficultyLabel,
  interviewTypeHint,
  interviewTypeLabel,
  levelLabel,
  modeHint,
  modeLabel,
} from "../labels";

const TYPES = Object.keys(interviewTypeLabel) as InterviewType[];
const DIFFICULTIES = Object.keys(difficultyLabel) as Difficulty[];
const MODES = Object.keys(modeLabel) as Mode[];
const LEVELS = Object.keys(levelLabel) as Level[];
const DURATIONS: SessionConfig["duration_min"][] = [30, 45];

function pick<T extends string>(value: string | null, options: T[], fallback: T): T {
  return options.includes(value as T) ? (value as T) : fallback;
}

function Choices<T extends string>(props: {
  legend: string;
  name: string;
  options: T[];
  value: T;
  onChange: (v: T) => void;
  label: (v: T) => string;
  hint?: (v: T) => string;
}) {
  return (
    <fieldset>
      <legend className="label">{props.legend}</legend>
      <div className="choices">
        {props.options.map((o) => (
          <label key={o} className="choice">
            <input
              type="radio"
              name={props.name}
              value={o}
              checked={props.value === o}
              onChange={() => props.onChange(o)}
            />
            <span className="choice__name">{props.label(o)}</span>
            {props.hint && <span className="choice__hint">{props.hint(o)}</span>}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** Journey 2, step 1: type, difficulty, duration and mode. */
export function SessionSetupPage() {
  const { jobId = "" } = useParams();
  const [params] = useSearchParams();
  const job = useJob(jobId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [type, setType] = useState<InterviewType>(pick(params.get("type"), TYPES, "behavioral"));
  const [difficulty, setDifficulty] = useState<Difficulty>(pick(params.get("difficulty"), DIFFICULTIES, "realistic"));
  const [duration, setDuration] = useState<SessionConfig["duration_min"]>(30);
  const [mode, setMode] = useState<Mode>("realistic");
  const [level, setLevel] = useState<Level | "">("");

  const start = useMutation({
    mutationFn: (config: SessionConfig) => sessionsApi.create({ job_target_id: jobId, config, channel: "voice" }),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: keys.usage });
      navigate(`/sessions/${session.id}/live`);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 402) {
        void queryClient.invalidateQueries({ queryKey: keys.usage });
        navigate(`/upgrade?reason=${encodeURIComponent(err.code ?? "upgrade_required")}`);
      }
    },
  });

  if (job.isPending) return <Loading />;
  if (job.isError) return <ErrorNotice error={job.error} />;

  const chosenLevel: Level | "" = level || job.data.level || "";
  const posting = job.data.posting;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!chosenLevel) return;
    start.mutate({ interview_type: type, difficulty, mode, duration_min: duration, level: chosenLevel });
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
          hint={(v) => interviewTypeHint[v]}
        />
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
        <Choices
          legend="Duration"
          name="duration"
          options={DURATIONS.map(String) as ("30" | "45")[]}
          value={String(duration) as "30" | "45"}
          onChange={(v) => setDuration(Number(v) as SessionConfig["duration_min"])}
          label={(v) => `${v} minutes`}
        />
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
        {start.isError && !(start.error instanceof ApiError && start.error.status === 402) && (
          <ErrorNotice error={start.error} />
        )}
        <div className="row section">
          <button type="submit" className="btn" disabled={start.isPending || !chosenLevel}>
            Start interview
          </button>
        </div>
      </form>
    </div>
  );
}
