import { useId, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";

import {
  ACTIVE_STATUSES,
  FINISHED_STATUSES,
  MAX_PASTED_CHARS,
  runAgainValues,
  simApi,
  useCancelRun,
  useDeleteRun,
  useKeepRun,
  useSimOptions,
  useSimRuns,
  useStartRun,
  type SimBehavior,
  type SimLevel,
  type SimOptions,
  type SimQuality,
  type SimRun,
  type SimRunFilters,
  type SimRunIn,
  type SimRunStatus,
} from "../api/sim";
import type { Difficulty, InterviewType, Mode } from "../api/types";
import { ReasonDialog } from "../components/ReasonDialog";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { clock, utc } from "../format";
import {
  behaviorLabel,
  difficultyLabel,
  levelLabel,
  interviewTypeLabel,
  modeLabel,
  qualityLabel,
  simStatusLabel,
} from "../labels";

type Channel = "voice" | "text";

function usd(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `$${value.toFixed(2)}`;
}

function Select<T extends string | number>({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; disabled?: boolean }[];
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={String(value)}
        disabled={disabled}
        onChange={(e) => {
          const picked = options.find((o) => String(o.value) === e.target.value);
          if (picked) onChange(picked.value);
        }}
      >
        {options.map((o) => (
          <option key={String(o.value)} value={String(o.value)} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** SM-1, SM-2, SM-3: one interview; the posting and level follow the persona. */
function emptyRun(options: SimOptions): Required<SimRunIn> {
  return {
    persona: options.personas[0]?.id ?? "",
    interview_type: "behavioral",
    difficulty: "realistic",
    mode: "realistic",
    duration_min: 30,
    quality: "average",
    behavior: "normal",
    channel: "voice",
    job_text: null,
    cv_text: null,
    level: null,
  };
}

function PastedText({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const id = useId();
  const length = value?.length ?? 0;
  return (
    <div className="field">
      <label htmlFor={id}>{label} (optional)</label>
      <textarea
        id={id}
        rows={6}
        maxLength={MAX_PASTED_CHARS}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
      />
      <span className="muted small">
        {length.toLocaleString()} / {MAX_PASTED_CHARS.toLocaleString()} characters
      </span>
    </div>
  );
}

/** SM-1..SM-3, SM-17, SM-18: one interview. A pasted job or CV replaces its half of the persona. */
function NewRunForm({ options, initial }: { options: SimOptions; initial: Required<SimRunIn> }) {
  const start = useStartRun();
  const [run, setRun] = useState<Required<SimRunIn>>(initial);
  const set = <K extends keyof SimRunIn>(key: K, value: Required<SimRunIn>[K]) =>
    setRun((r) => ({ ...r, [key]: value }));
  const voiceOnly = new Set(options.behaviors.filter((b) => b.voice_only).map((b) => b.id));
  const persona = options.personas.find((p) => p.id === run.persona);
  const estimate = options.estimates.find((e) => e.duration_min === run.duration_min);
  const queueFull = options.queue.waiting >= options.queue.max_waiting;
  const shortOfBudget = options.budget !== null && estimate !== undefined && options.budget.left_usd < estimate.total_usd;
  const pastedJob = (run.job_text ?? "").trim() !== "";
  const pastedCv = (run.cv_text ?? "").trim() !== "";
  const needsLevel = pastedJob && !run.level;

  const changeChannel = (channel: Channel) =>
    setRun((r) => ({ ...r, channel, behavior: channel === "text" && voiceOnly.has(r.behavior) ? "normal" : r.behavior }));

  return (
    <section className="panel section" aria-labelledby="new-run">
      <h2 id="new-run">New run</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          start.mutate({ ...run, level: pastedJob ? run.level : null });
        }}
      >
        <div className="form-grid">
          <Select
            label="Persona"
            value={run.persona}
            options={options.personas.map((p) => ({ value: p.id, label: p.label }))}
            onChange={(v) => set("persona", v)}
          />
          <Select<Channel>
            label="Channel"
            value={run.channel}
            options={options.channels.map((c) => ({ value: c, label: c === "voice" ? "Voice" : "Text" }))}
            onChange={changeChannel}
          />
          <Select<InterviewType>
            label="Interview type"
            value={run.interview_type}
            options={options.interview_types.map((t) => ({ value: t, label: interviewTypeLabel[t] }))}
            onChange={(v) => set("interview_type", v)}
          />
          <Select<Difficulty>
            label="Difficulty"
            value={run.difficulty}
            options={options.difficulties.map((d) => ({ value: d, label: difficultyLabel[d] }))}
            onChange={(v) => set("difficulty", v)}
          />
          <Select<Mode>
            label="Mode"
            value={run.mode}
            options={options.modes.map((m) => ({ value: m, label: modeLabel[m] }))}
            onChange={(v) => set("mode", v)}
          />
          <Select<number>
            label="Length"
            value={run.duration_min}
            options={options.durations.map((d) => ({ value: d, label: `${d} min${d === 10 ? " (mini)" : ""}` }))}
            onChange={(v) => set("duration_min", v as Required<SimRunIn>["duration_min"])}
          />
          <Select<SimQuality>
            label="Candidate quality"
            value={run.quality}
            options={options.qualities.map((q) => ({ value: q, label: qualityLabel[q] }))}
            onChange={(v) => set("quality", v)}
          />
          <Select<SimBehavior>
            label="Behavior"
            value={run.behavior}
            options={options.behaviors.map((b) => ({
              value: b.id,
              label: `${behaviorLabel[b.id]}${b.voice_only ? " (voice only)" : ""}`,
              disabled: b.voice_only && run.channel !== "voice",
            }))}
            onChange={(v) => set("behavior", v)}
          />
        </div>
        <fieldset className="section">
          <legend>Job and CV</legend>
          <p className="muted small">
            Each is optional and replaces only its half of the persona. Use synthetic or public texts; never a real
            candidate&rsquo;s CV.
          </p>
          <div className="grid-2">
            <PastedText label="Job posting" value={run.job_text} onChange={(v) => set("job_text", v)} />
            <PastedText label="CV" value={run.cv_text} onChange={(v) => set("cv_text", v)} />
          </div>
          {pastedJob && (
            <Select<SimLevel | "">
              label="Level (required with a pasted job)"
              value={run.level ?? ""}
              options={[
                { value: "", label: "Choose a level" },
                ...(Object.keys(levelLabel) as SimLevel[]).map((l) => ({ value: l, label: levelLabel[l] })),
              ]}
              onChange={(v) => set("level", v || null)}
            />
          )}
        </fieldset>
        {persona && (
          <p className="muted small">
            {pastedJob ? "Pasted job" : <>Posting <code>{persona.posting}</code></>},{" "}
            {pastedCv ? "pasted CV" : `CV of the ${persona.label.toLowerCase()} persona`}, level{" "}
            {pastedJob ? (run.level ? levelLabel[run.level] : "not chosen") : persona.level.replace(/_/g, " ")}.
          </p>
        )}
        <dl className="dl">
          <dt>Estimate</dt>
          <dd>
            {estimate ? `about ${usd(estimate.total_usd)}` : "-"}
            {estimate && (
              <span className="muted small">
                {" "}
                (candidate {usd(estimate.candidate_usd)}, judge {usd(estimate.judge_usd)}, interviewer and scorer{" "}
                {usd(estimate.main_server_usd)})
              </span>
            )}
          </dd>
          <dt>Sim budget today</dt>
          <dd>
            {options.budget
              ? `${usd(options.budget.left_usd)} left of ${usd(options.budget.limit_usd)}`
              : "Unknown (the sim key does not report a budget)"}
          </dd>
          <dt>Queue</dt>
          <dd>
            {options.queue.active} running, {options.queue.waiting} of {options.queue.max_waiting} waiting
          </dd>
        </dl>
        <GateNotice options={options} shortOfBudget={shortOfBudget} />
        {start.isError && <ErrorNotice error={start.error} title="The run did not start." />}
        {start.isSuccess && (
          <p className="notice" role="status">
            Run queued: {start.data.scenario.candidate_name ?? "the AI candidate"}, {start.data.scenario.duration_min} min.
          </p>
        )}
        <button
          type="submit"
          className="btn btn--primary"
          disabled={start.isPending || !options.gate.ok || queueFull || !run.persona || needsLevel}
        >
          {start.isPending ? "Starting" : "Start run"}
        </button>
      </form>
    </section>
  );
}

function GateNotice({ options, shortOfBudget }: { options: SimOptions; shortOfBudget: boolean }) {
  const { gate, queue } = options;
  const lines: ReactNode[] = [];
  if (!gate.ok) {
    lines.push(
      <>
        {gate.reason}
        {gate.retry ? "." : ". "}
        {!gate.retry && /paused/i.test(gate.reason ?? "") && <Link to="/ops/controls">Open Controls</Link>}
      </>,
    );
  }
  if (queue.waiting >= queue.max_waiting) lines.push(`${queue.waiting} runs are waiting; the queue is full.`);
  if (shortOfBudget) lines.push("The estimate is more than the budget left today; Start will be refused.");
  if (lines.length === 0) return <p className="muted small">Runs can start now.</p>;
  return (
    <div className="notice" role="status" aria-label="Why a run cannot start">
      {lines.map((l, i) => (
        <p key={i}>{l}</p>
      ))}
    </div>
  );
}

function Filters({ filters, onChange }: { filters: SimRunFilters; onChange: (f: SimRunFilters) => void }) {
  const statuses = Object.keys(simStatusLabel) as SimRunStatus[];
  return (
    <div className="filters section" role="group" aria-label="Filter runs">
      <Select<SimRunStatus | "">
        label="Status"
        value={filters.status ?? ""}
        options={[{ value: "", label: "Any" }, ...statuses.map((s) => ({ value: s, label: simStatusLabel[s] }))]}
        onChange={(v) => onChange({ ...filters, status: v || undefined })}
      />
      <Select<Channel | "">
        label="Channel"
        value={filters.channel ?? ""}
        options={[
          { value: "", label: "Any" },
          { value: "voice", label: "Voice" },
          { value: "text", label: "Text" },
        ]}
        onChange={(v) => onChange({ ...filters, channel: v || undefined })}
      />
      <Select<"admin" | "suite" | "">
        label="Started by"
        value={filters.source ?? ""}
        options={[
          { value: "", label: "Anyone" },
          { value: "admin", label: "An admin" },
          { value: "suite", label: "A suite (sim-run.ps1)" },
        ]}
        onChange={(v) => onChange({ ...filters, source: v || undefined })}
      />
    </div>
  );
}

function summary(run: SimRun): string {
  const s = run.scenario;
  const type = interviewTypeLabel[s.interview_type as InterviewType] ?? s.interview_type;
  const behavior = behaviorLabel[s.behavior as SimBehavior] ?? s.behavior;
  const custom = [s.custom_job && "custom job", s.custom_cv && "custom CV"].filter(Boolean).join(", ");
  const base = `${s.persona} · ${type} · ${s.channel} · ${s.duration_min} min · ${s.quality} · ${behavior}`;
  return custom ? `${base} · ${custom}` : base;
}

function Length({ run }: { run: SimRun }) {
  if (run.status === "interviewing") {
    return (
      <>
        {clock(run.progress_s * 1000)} / {run.scenario.duration_min} min
      </>
    );
  }
  return <>{run.progress_s > 0 ? clock(run.progress_s * 1000) : "-"}</>;
}

type Pending = { kind: "cancel" | "delete"; run: SimRun };

/** SM-12: admin runs and suite runs; SM-4: refreshed every 5 s while a run is not finished. */
function RunsTable({ filters, onRunAgain }: { filters: SimRunFilters; onRunAgain: (run: SimRun) => void }) {
  const runs = useSimRuns(filters);
  const keep = useKeepRun();
  const cancel = useCancelRun();
  const remove = useDeleteRun();
  const [pending, setPending] = useState<Pending | null>(null);
  const close = () => setPending(null);
  const write = pending?.kind === "cancel" ? cancel : remove;

  if (runs.isPending) return <Loading label="Loading the runs" />;
  if (runs.isError) return <ErrorNotice error={runs.error} />;
  if (runs.data.runs.length === 0) return <p>No runs yet.</p>;

  return (
    <>
      {keep.isError && <ErrorNotice error={keep.error} />}
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Simulation runs, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Started</th>
              <th scope="col">Scenario</th>
              <th scope="col">Status</th>
              <th scope="col">Length</th>
              <th scope="col">Hire signal</th>
              <th scope="col">Failed rules</th>
              <th scope="col">p50 response</th>
              <th scope="col">Cost</th>
              <th scope="col">Keep</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.runs.map((run) => {
              const deleted = run.deleted_at !== null;
              const finished = FINISHED_STATUSES.includes(run.status);
              const canReplay = run.session_id !== null && run.files && !deleted;
              return (
                <tr key={run.id} data-status={run.status}>
                  <td>
                    {utc(run.created_at)}
                    <br />
                    <span className="muted small">
                      {run.source === "suite" ? `suite ${run.suite ?? ""}` : (run.created_by ?? "-")}
                    </span>
                  </td>
                  <td>
                    {run.scenario.candidate_name && <strong>{run.scenario.candidate_name} </strong>}
                    <span className="small">{summary(run)}</span>
                  </td>
                  <td>
                    <span className="status-pill" data-status={run.status}>
                      {simStatusLabel[run.status]}
                    </span>
                    {run.status_reason && <div className="muted small">{run.status_reason}</div>}
                    {deleted && (
                      <div className="muted small">
                        Files deleted by {run.deleted_by}
                        {run.delete_reason ? `: ${run.delete_reason}` : ""}
                      </div>
                    )}
                  </td>
                  <td className="num">
                    <Length run={run} />
                  </td>
                  <td>{run.hire_signal ?? "-"}</td>
                  <td>{run.failed_rules.length > 0 ? run.failed_rules.join(", ") : finished ? "None" : "-"}</td>
                  <td className="num">
                    {run.latency_p50_ms !== null ? `${Math.round(run.latency_p50_ms)} ms` : "-"}
                  </td>
                  <td className="num">{usd(run.cost_total_usd)}</td>
                  <td>
                    {run.source === "admin" && !deleted ? (
                      <input
                        type="checkbox"
                        aria-label={`Keep run ${run.scenario.candidate_name ?? run.id}`}
                        checked={run.keep}
                        disabled={keep.isPending}
                        onChange={(e) => keep.mutate({ id: run.id, keep: e.target.checked })}
                      />
                    ) : (
                      "-"
                    )}
                  </td>
                  <td className="row row--tight">
                    {canReplay && (
                      <Link className="btn btn--small" to={`/simulations/replay/${run.session_id}`}>
                        Replay
                      </Link>
                    )}
                    {run.source === "admin" && (
                      <button type="button" className="btn btn--small" onClick={() => onRunAgain(run)}>
                        Run again
                      </button>
                    )}
                    {run.source === "admin" && !finished && (
                      <button
                        type="button"
                        className="btn btn--small btn--danger"
                        onClick={() => {
                          cancel.reset();
                          setPending({ kind: "cancel", run });
                        }}
                      >
                        Cancel
                      </button>
                    )}
                    {run.source === "admin" && finished && !deleted && (
                      <button
                        type="button"
                        className="btn btn--small btn--danger"
                        onClick={() => {
                          remove.reset();
                          setPending({ kind: "delete", run });
                        }}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {pending && (
        <ReasonDialog
          title={pending.kind === "cancel" ? "Cancel the run" : "Delete the run"}
          confirmLabel={pending.kind === "cancel" ? "Cancel run" : "Delete run"}
          danger
          requireWord={pending.kind === "delete" && pending.run.keep ? "DELETE" : undefined}
          pending={write.isPending}
          error={write.isError ? write.error : undefined}
          onCancel={close}
          onConfirm={(reason) =>
            pending.kind === "cancel"
              ? cancel.mutate({ id: pending.run.id, reason }, { onSuccess: close })
              : remove.mutate({ id: pending.run.id, reason }, { onSuccess: close })
          }
        >
          <p>{summary(pending.run)}</p>
          {pending.kind === "cancel" ? (
            ACTIVE_STATUSES.includes(pending.run.status) ? (
              <p>The interview ends within a few seconds. Its transcript and audio so far are kept; it is not judged.</p>
            ) : (
              <p>The run has not started; it leaves the queue now.</p>
            )
          ) : (
            <p>
              The run folder (transcript, audio, judge) is deleted now. The row stays in this list with its cost, and the
              interview stays in Interviews.
              {pending.run.keep && " This run is marked Keep."}
            </p>
          )}
        </ReasonDialog>
      )}
    </>
  );
}

/** Simulations (SM): start an AI candidate interview, follow it, and open its replay. */
export function SimulationsPage() {
  const options = useSimOptions();
  const [filters, setFilters] = useState<SimRunFilters>({});
  const [prefill, setPrefill] = useState<{ key: number; values: Required<SimRunIn>; from: SimRun } | null>(null);
  const [againError, setAgainError] = useState<unknown>(null);
  const formRef = useRef<HTMLDivElement>(null);

  /** SM-21: the run's settings and pasted texts (fetched: the list does not carry the texts). */
  const runAgain = async (run: SimRun) => {
    setAgainError(null);
    try {
      const full = await simApi.run(run.id);
      setPrefill({ key: Date.now(), values: runAgainValues(full), from: full });
      formRef.current?.scrollIntoView?.({ block: "start" });
    } catch (err) {
      setAgainError(err);
    }
  };
  const textsGone = (run: SimRun) => run.deleted_at !== null && (run.scenario.custom_job || run.scenario.custom_cv);
  return (
    <>
      <PageHead title="Simulations">
        <p>
          The AI interviewer and the AI candidate in a real interview, run in the background on the main server. One
          runs at a time.
        </p>
      </PageHead>
      {options.isPending && <Loading label="Loading the form" />}
      {options.isError && <ErrorNotice error={options.error} />}
      <div ref={formRef}>
        {againError !== null && <ErrorNotice error={againError} title="The run could not be loaded." />}
        {prefill && (
          <p className="notice" role="status">
            Filled in from the run of {prefill.from.scenario.candidate_name ?? "the AI candidate"},{" "}
            {utc(prefill.from.created_at)}.
            {textsGone(prefill.from) && " Its pasted texts were deleted, so only its settings are filled in."} Change
            anything before Start.
          </p>
        )}
        {options.data && (
          <NewRunForm
            key={prefill?.key ?? 0}
            options={options.data}
            initial={prefill?.values ?? emptyRun(options.data)}
          />
        )}
      </div>
      <section className="section" aria-labelledby="runs">
        <h2 id="runs">Runs</h2>
        <Filters filters={filters} onChange={setFilters} />
        <RunsTable filters={filters} onRunAgain={(run) => void runAgain(run)} />
      </section>
    </>
  );
}
