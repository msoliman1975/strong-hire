/**
 * RH-3 (mockup #interview): one interview (role x resume x type). Readiness (or the first-take
 * empty state), skill coverage, the next take with "Strova will act as …" and a settings drawer
 * (difficulty, mode, tone, length with the paywall rules), and the takes, each opening its debrief.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { keys, useJob, useProfile, useResumes, useUsage } from "../../api/hooks";
import { gapApi } from "../../api/gap";
import { useInterview } from "../../api/roles";
import { paywallReason, sessionsApi } from "../../api/sessions";
import type { Difficulty, HireSignal, InterviewDetail, Level, Mode } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { competencyLabel, difficultyLabel, formatDate, modeHintV2, modeLabelV2 } from "../../labels";
import type { Tone } from "../plan/api";
import { DEFAULT_TAKE_MINUTES, roleTitle, rolePath, typeName } from "../roles/shared";

const MINI = DEFAULT_TAKE_MINUTES;
const LENGTHS = [10, 30, 45] as const;
const DIFFICULTIES: Difficulty[] = ["friendly", "realistic", "tough"];
const MODES: Mode[] = ["realistic", "coach"];
const TONES: Tone[] = ["as_company", "warm", "neutral", "direct"];

const toneWord = (tone: Tone, company: string | null) =>
  tone === "as_company" ? `As ${company ?? "the company"}` : { warm: "Warm", neutral: "Neutral", direct: "Direct" }[tone];

function Seg<T extends string | number>({
  label,
  value,
  options,
  name,
  onChange,
  disabled,
}: {
  label: string;
  value: T;
  options: readonly T[];
  name: (v: T) => string;
  onChange: (v: T) => void;
  disabled?: (v: T) => boolean;
}) {
  return (
    <div className="sx-stack" style={{ gap: 6 }}>
      <strong className="sx-small">{label}</strong>
      <div className="sx-seg" role="group" aria-label={label}>
        {options.map((o) => (
          <button key={String(o)} type="button" aria-pressed={o === value} onClick={() => onChange(o)} disabled={disabled?.(o)}>
            {name(o)}
          </button>
        ))}
      </div>
    </div>
  );
}

function signalClass(s: HireSignal | null): string {
  if (!s) return "sx-muted";
  if (s === "Strong Hire" || s === "Hire") return "sx-signal-hire";
  if (s === "Lean Hire") return "sx-signal-lean";
  return "sx-signal-no";
}

function chipFor(score: number | null): string {
  if (score === null) return "";
  if (score >= 3) return " ok";
  if (score >= 2) return " warn";
  return " bad";
}

export function InterviewPage() {
  const { interviewId = "" } = useParams();
  const data = useInterview(interviewId);
  if (data.isPending) return <Loading label="Loading the interview" />;
  if (data.isError) return <ErrorNotice error={data.error} />;
  return <InterviewBody detail={data.data} />;
}

function InterviewBody({ detail }: { detail: InterviewDetail }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const usage = useUsage();
  const profile = useProfile();
  const resumes = useResumes();
  const job = useJob(detail.interview.job_target_id, false);
  const fullAllowed = usage.data?.full_interviews_allowed ?? false;
  const company = detail.role.company_name;
  const [open, setOpen] = useState(false);
  const [difficulty, setDifficulty] = useState<Difficulty>("realistic");
  const [mode, setMode] = useState<Mode>("realistic");
  const [tone, setTone] = useState<Tone>("as_company");
  const [length, setLength] = useState<(typeof LENGTHS)[number]>(MINI);
  const ready = detail.readiness;
  const score = ready.score;
  const name = typeName(detail.interview);
  const level: Level | null = job.data?.level ?? profile.data?.target_level ?? null;
  const resume = resumes.data?.find((r) => r.id === detail.interview.resume_id);

  const start = useMutation({
    mutationFn: async () => {
      // A new role's gap analysis runs in the background; the take needs it ready.
      if (detail.interview.resume_id) await gapApi.whenReady(detail.interview.job_target_id, detail.interview.resume_id);
      return sessionsApi.create({
        job_target_id: detail.interview.job_target_id,
        interview_id: detail.interview.id,
        resume_id: detail.interview.resume_id,
        channel: "voice",
        config: {
          interview_type: detail.interview.interview_type,
          difficulty,
          mode,
          duration_min: length,
          level: level ?? "mid",
          tone,
          custom: detail.interview.custom ?? null,
        },
      });
    },
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: keys.usage });
      navigate(`/sessions/${session.id}/live`);
    },
    onError: (err) => {
      const reason = paywallReason(err, detail.interview.interview_type === "custom");
      if (reason) navigate(`/upgrade?reason=${encodeURIComponent(reason)}`);
    },
  });

  const takeNo = detail.takes.length + 1;
  const setup = `${modeLabelV2[mode]}, ${length} minutes, ${toneWord(tone, company).replace(/^As /, "")} tone.`;
  const actingAs = detail.interview.acting_as.text.replace(/^Strova is acting as /, "Strova will act as ");
  const coverage: ReactNode =
    ready.takes_counted === 0 ? (
      <p className="sx-small sx-muted">Shows after your first Realistic take.</p>
    ) : (
      <div className="sx-chips">
        {ready.competencies.map((c) => (
          <span key={c.competency} className={`sx-chip${chipFor(c.score)}`}>
            {competencyLabel(c.competency)} · {c.score === null ? "not asked yet" : c.score.toFixed(1)}
          </span>
        ))}
      </div>
    );

  return (
    <div className="sx-page">
      <div className="sx-stack" style={{ gap: 6 }}>
        <Link className="sx-small" to={rolePath(detail.role.id)}>
          {roleTitle(detail.role)}
        </Link>
        <h1>{name} interview</h1>
        <p className="sx-muted sx-small">
          Role × Resume × Type: {company ?? detail.role.name ?? "Role"} · {detail.resume_name ?? resume?.name ?? "Resume"} · {name}
        </p>
      </div>
      <div className="sx-grid2">
        <section className="sx-card interviewer" aria-label="Readiness">
          <div className="sx-eyebrow teal">Readiness</div>
          {score === null ? (
            <>
              <div className="sx-row" style={{ alignItems: "baseline" }}>
                <span className="sx-score sx-muted">–</span>
                <span className="sx-muted">goal {ready.goal}</span>
              </div>
              <div className="sx-bar">
                <span style={{ width: "0%" }} />
              </div>
              <p className="sx-small sx-muted">Your readiness appears after your first Realistic take.</p>
            </>
          ) : (
            <>
              <div className="sx-row" style={{ alignItems: "baseline" }}>
                <span className="sx-score">{score}</span>
                <span className="sx-muted">of 100 · goal {ready.goal}</span>
                {ready.change !== null && ready.change !== 0 && (
                  <span className={`sx-chip ${ready.change > 0 ? "ok" : "warn"}`}>
                    {ready.change > 0 ? "+" : ""}
                    {ready.change} after your last take
                  </span>
                )}
              </div>
              <div className="sx-bar">
                <span style={{ width: `${score}%` }} />
              </div>
              <p className="sx-small sx-muted">
                A practice estimate from your Realistic takes. It is not a prediction of {company ?? "the company"}'s decision.
              </p>
            </>
          )}
        </section>
        <section className="sx-card" aria-label="Skill coverage">
          <div className="sx-eyebrow plain">Skill coverage</div>
          {coverage}
          <p className="sx-small sx-muted">For information. Scores out of 4 from Realistic takes.</p>
        </section>
      </div>
      <section className="sx-hero" aria-label="Next take">
        <div className="sx-row" style={{ gap: 8 }}>
          <Strova mode="interviewing" size={22} />
          <span className="sx-eyebrow" style={{ color: "var(--sh-teal-light)" }}>
            Take {takeNo}
          </span>
        </div>
        <div className="big">{setup}</div>
        <div className="sub">{actingAs}.</div>
        <div className="sx-row">
          <button type="button" className="sx-btn" onClick={() => start.mutate()} disabled={start.isPending}>
            {start.isPending ? "Getting the take ready…" : detail.takes.length === 0 ? "Start the first take" : "Retake"}
          </button>
          <button type="button" className="sx-btn ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "Hide settings" : "Change settings"}
          </button>
        </div>
        {start.isError && paywallReason(start.error, false) === null && <ErrorNotice error={start.error} />}
        {open && (
          <div className="sx-drawer" data-testid="take-settings">
            <Seg label="Difficulty" value={difficulty} options={DIFFICULTIES} name={(d) => difficultyLabel[d]} onChange={setDifficulty} />
            <div className="sx-stack" style={{ gap: 6 }}>
              <Seg label="Mode" value={mode} options={MODES} name={(m) => modeLabelV2[m]} onChange={setMode} />
              <span className="sx-small sx-muted">{modeHintV2.coach.replace("Pause, ask", "Practice lets you pause, ask")}</span>
            </div>
            <Seg label="Tone" value={tone} options={TONES} name={(t) => toneWord(t, company)} onChange={setTone} />
            <div className="sx-stack" style={{ gap: 6 }}>
              <Seg
                label="Length"
                value={length}
                options={LENGTHS}
                name={(n) => `${n} min`}
                onChange={setLength}
                disabled={(n) => n !== MINI && !fullAllowed}
              />
              {!fullAllowed && <span className="sx-small sx-muted">30 and 45 minutes need a subscription.</span>}
            </div>
          </div>
        )}
      </section>
      <section className="sx-card" aria-labelledby="takes-heading">
        <h2 id="takes-heading">Takes</h2>
        {detail.takes.length === 0 && (
          <p className="sx-small sx-muted">No takes yet. Your first take sets your starting readiness.</p>
        )}
        {detail.takes.map((t) => (
          <Link key={t.session_id} className="sx-list-row" to={`/sessions/${t.session_id}/debrief`}>
            <div className="sx-stack" style={{ gap: 2 }}>
              <strong>
                Take {t.number} · {modeLabelV2[t.mode]}
              </strong>
              <span className="sx-small sx-muted">
                {formatDate(t.at)} ·{" "}
                {t.mode === "coach"
                  ? "not counted"
                  : t.scored !== null
                    ? `${t.met_bar} of ${t.scored} met the bar`
                    : t.status === "completed"
                      ? "scoring"
                      : t.status.replace("_", " ")}
              </span>
            </div>
            <span className={signalClass(t.hire_signal)}>{t.mode === "coach" ? "Practice" : (t.hire_signal ?? "–")}</span>
          </Link>
        ))}
      </section>
    </div>
  );
}
