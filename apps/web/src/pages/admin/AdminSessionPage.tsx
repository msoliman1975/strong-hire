import { Link, useParams } from "react-router";

import { type AdminSession, type AdminTrace, useAdminSession } from "../../api/admin";
import { ErrorNotice, Loading, PageHead } from "../../components/ui";
import { difficultyLabel, interviewTypeLabel, modeLabel, phaseLabel } from "../../labels";
import { clock, money, utc, words } from "./format";

function Metadata({ session: s }: { session: AdminSession }) {
  return (
    <dl className="dl panel">
      <dt>User</dt>
      <dd>{s.user_email ?? "-"}</dd>
      <dt>Date</dt>
      <dd>{utc(s.created_at)}</dd>
      <dt>Type</dt>
      <dd>{interviewTypeLabel[s.interview_type]}</dd>
      <dt>Setup</dt>
      <dd>
        {difficultyLabel[s.difficulty]}, {modeLabel[s.mode]}, {s.channel}
      </dd>
      <dt>Length</dt>
      <dd>
        {s.duration_s === null ? "Not ended" : clock(s.duration_s * 1000)} of {s.duration_min} minutes planned
      </dd>
      <dt>Minutes billed</dt>
      <dd>{s.minutes_billed}</dd>
      <dt>Status</dt>
      <dd>{words(s.status)}</dd>
      <dt>Hire signal</dt>
      <dd>{s.hire_signal ?? "-"}</dd>
      <dt>Scores</dt>
      <dd>
        {s.scores.length === 0
          ? "-"
          : s.scores.map((c) => `${words(c.competency)} ${c.score} of 4`).join("; ")}
      </dd>
      <dt>Cost</dt>
      <dd>
        {money(s.cost_usd)}
        {s.cost_source !== "none" && <span className="muted"> (from {words(s.cost_source)})</span>}
      </dd>
      <dt>Model</dt>
      <dd>
        {s.model_profile ?? "-"} / {s.interviewer_model_id ?? "-"}
      </dd>
      <dt>Prompts</dt>
      <dd>{s.prompt_version ?? "-"}</dd>
    </dl>
  );
}

function reasonText(trace: AdminTrace): string {
  const reason = trace.reason ?? {};
  const parts: string[] = [];
  const why = reason.why;
  if (Array.isArray(why) && why.length > 0) parts.push(why.map((w) => words(String(w))).join(", then "));
  const decision = reason.decision as { action?: string; missing?: string[] } | null | undefined;
  if (decision?.action) {
    const missing = decision.missing?.length ? ` (missing: ${decision.missing.map(words).join(", ")})` : "";
    parts.push(`model said ${words(decision.action)}${missing}`);
  }
  if (typeof reason.turns_taken_back === "number") parts.push(`${reason.turns_taken_back} turns taken back`);
  return parts.join("; ") || "-";
}

function TraceItem({ trace: t }: { trace: AdminTrace }) {
  const reason = t.reason ?? {};
  const left = typeof reason.time_left_in_phase_ms === "number" ? reason.time_left_in_phase_ms : null;
  const probes =
    typeof reason.probes_used === "number" && typeof reason.probe_limit === "number"
      ? `${reason.probes_used} of ${reason.probe_limit}`
      : null;
  return (
    <li className="trace" data-call={t.call} data-error={t.error ? "true" : undefined}>
      <h3>
        {t.seq}. {words(t.move)} <span className="muted">({t.call})</span>
      </h3>
      <dl className="dl">
        <dt>Reason</dt>
        <dd>{reasonText(t)}</dd>
        <dt>Timer</dt>
        <dd>
          {phaseLabel[t.phase]} at {clock(t.elapsed_ms)}, phase ends at {clock(t.phase_deadline_ms)}
          {left !== null && `, ${clock(left)} left`}
          {probes && `, follow-ups ${probes}`}
        </dd>
        {t.question_ref && (
          <>
            <dt>Question</dt>
            <dd>{t.question_ref}</dd>
          </>
        )}
        {t.spoken_text && (
          <>
            <dt>Said</dt>
            <dd>{t.spoken_text}</dd>
          </>
        )}
        {t.model && (
          <>
            <dt>Model</dt>
            <dd>
              {t.model}, {t.input_tokens} in, {t.output_tokens} out, {t.latency_ms ?? "-"} ms, {money(t.cost_usd)}
            </dd>
          </>
        )}
        {t.error && (
          <>
            <dt>Error</dt>
            <dd>{t.error}</dd>
          </>
        )}
      </dl>
      {t.messages && t.messages.length > 0 && (
        <details>
          <summary>Prompt ({t.messages.length} messages)</summary>
          {t.messages.map((m, i) => (
            <div key={i}>
              <p className="label">
                {m.role}
                {m.prompt_ref ? ` (${m.prompt_ref})` : ""}
              </p>
              <pre>{m.content}</pre>
            </div>
          ))}
        </details>
      )}
      {t.raw_reply !== null && (
        <details>
          <summary>Raw reply</summary>
          <pre>{t.raw_reply}</pre>
        </details>
      )}
    </li>
  );
}

/** One interview (R2). Transcript and traces only when the user's consent is on. */
export function AdminSessionPage() {
  const { sessionId = "" } = useParams();
  const detail = useAdminSession(sessionId);

  if (detail.isPending) return <Loading label="Loading the interview" />;
  if (detail.isError) return <ErrorNotice error={detail.error} title="The interview could not be loaded." />;
  const { session, content_visible, transcript, traces, trace_retention_days } = detail.data;

  return (
    <>
      <PageHead title="Interview">
        <p>
          <Link to="/admin/interviews">Back to interviews</Link>
        </p>
      </PageHead>
      <Metadata session={session} />

      {!content_visible && (
        <div className="notice section" role="status">
          <p>This user has not given consent. You can see the details above only.</p>
        </div>
      )}

      {content_visible && (
        <>
          <section className="section" aria-labelledby="transcript">
            <h2 id="transcript">Transcript</h2>
            {transcript && transcript.length > 0 ? (
              <ol className="transcript panel">
                {transcript.map((turn, i) => (
                  <li key={i}>
                    <span className="muted">{clock(turn.start_ms)} </span>
                    <span className="who">{turn.speaker === "interviewer" ? "Interviewer" : "Candidate"}:</span>
                    {turn.text}
                  </li>
                ))}
              </ol>
            ) : (
              <p>No transcript.</p>
            )}
          </section>
          <section className="section" aria-labelledby="traces">
            <h2 id="traces">Interviewer reasoning</h2>
            <p className="muted">
              One entry per interviewer model call or fixed line. Entries are deleted after {trace_retention_days} days.
            </p>
            {traces && traces.length > 0 ? (
              <ol className="trace-list">
                {traces.map((t) => (
                  <TraceItem key={t.seq} trace={t} />
                ))}
              </ol>
            ) : (
              <p>No entries. They were deleted, or the interview ran before they were kept.</p>
            )}
          </section>
        </>
      )}
    </>
  );
}
