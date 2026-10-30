/**
 * TG-2 (mockup #add-role): add a target role in one screen and three steps. 1 the job posting
 * (link or text, IN-1, IN-6), 2 check the role (company, title, level, optional interview date,
 * must-have skills), 3 the interviews Strova suggests (TG-3) against the main resume. "Create the
 * role" saves the role with its interviews (RH-1) and opens the role page; the gap analysis runs
 * in the background as before.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { gapApi } from "../../api/gap";
import { useJob, useJobTask, useResumes } from "../../api/hooks";
import { jobProblem, jobTargetsApi } from "../../api/inputs";
import { roleKeys, useSuggestedInterviews } from "../../api/roles";
import type { InterviewOut, JobPosting, Level } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { interviewTypeLabel, levelLabel } from "../../labels";
import { countWords, fmt, JD_MAX_WORDS, JD_WARN_WORDS } from "../../limits";
import { planApi } from "../plan/api";
import { rolePath } from "./shared";

type Step = 1 | 2 | 3;
type Kind = InterviewOut["interview_type"];
const STEPS = ["Job posting", "Check the role", "Interviews"] as const;
const LEVELS = Object.keys(levelLabel) as Level[];

function Steps({ step }: { step: Step }) {
  return (
    <ol className="sx-steps" aria-label="Add a target role steps">
      {STEPS.map((t, i) => {
        const n = i + 1;
        return (
          <li key={t} className={n < step ? "done" : n === step ? "on" : undefined} aria-current={n === step ? "step" : undefined}>
            {n} · {t}
          </li>
        );
      })}
    </ol>
  );
}

export function AddRolePage() {
  const [step, setStep] = useState<Step>(1);
  const [jobId, setJobId] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  return (
    <div className="sx-page" style={{ maxWidth: 780 }}>
      <div className="sx-stack" style={{ gap: 6 }}>
        <div className="sx-eyebrow teal">Target roles</div>
        <h1>Add a target role</h1>
      </div>
      <Steps step={step} />
      {step === 1 && (
        <PostingStep
          onRead={(id, task) => {
            setJobId(id);
            setTaskId(task);
          }}
          jobId={jobId}
          taskId={taskId}
          onNext={() => setStep(2)}
        />
      )}
      {step >= 2 && jobId && <RoleSteps jobId={jobId} step={step} setStep={setStep} />}
    </div>
  );
}

function PostingStep({
  jobId,
  taskId,
  onRead,
  onNext,
}: {
  jobId: string | null;
  taskId: string | null;
  onRead: (jobId: string, taskId: string | null) => void;
  onNext: () => void;
}) {
  const [link, setLink] = useState("");
  const [text, setText] = useState("");
  const [pasteChosen, setPaste] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const job = useJob(jobId ?? "", true);
  const task = useJobTask(jobId ?? "", taskId);
  const failed = jobProblem(task.data);
  // A link the worker cannot read (LinkedIn, a login wall) switches to the text field.
  const paste = pasteChosen || Boolean(failed?.needsPaste);
  const read = Boolean(jobId) && job.data?.status === "extracted";
  const create = useMutation({
    mutationFn: () => jobTargetsApi.create(paste ? { text: text.trim() } : { url: link.trim() }),
    onSuccess: (accepted) => onRead(accepted.job_target.id, accepted.job?.id ?? null),
    onError: (err) => {
      const detail = (err as { detail?: { code?: string } }).detail;
      if (detail?.code === "paste_required") setPaste(true);
    },
  });

  useEffect(() => {
    if (read) onNext();
  }, [read, onNext]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setProblem(null);
    if (paste ? !text.trim() : !link.trim()) {
      setProblem(paste ? "Paste the job posting text." : "Paste the link to the job posting.");
      return;
    }
    create.mutate();
  };

  const reading = create.isPending || (Boolean(jobId) && !failed && !read);
  const words = countWords(text);
  const tooLong = paste && words > JD_MAX_WORDS;
  return (
    <form className="sx-card" onSubmit={onSubmit} noValidate>
      {paste ? (
        <div className="sx-field">
          <label htmlFor="jobtext">Job posting text</label>
          <textarea id="jobtext" rows={8} value={text} onChange={(e) => setText(e.target.value)} aria-describedby="jobtext-count" />
          {/* IN-1: amber from 2,000 words, blocked past 2,500, as the API enforces. */}
          <p className="sx-small sx-muted" id="jobtext-count" data-level={tooLong ? "over" : words >= JD_WARN_WORDS ? "warn" : undefined} aria-live="polite">
            {fmt(words)} / {fmt(JD_MAX_WORDS)} words
            {tooLong && <span> · Trim the benefits and company boilerplate.</span>}
          </p>
        </div>
      ) : (
        <div className="sx-field">
          <label htmlFor="joblink">Job posting link</label>
          <input id="joblink" type="url" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://" />
        </div>
      )}
      <p className="sx-small sx-muted">
        {paste ? (
          <>
            Paste the whole posting: the role, the requirements and the company.{" "}
            <button type="button" className="sx-link" onClick={() => setPaste(false)}>
              Use a link instead
            </button>
          </>
        ) : (
          <>
            Greenhouse, Lever, Ashby, Workday and most career pages work. For LinkedIn,{" "}
            <button type="button" className="sx-link" onClick={() => setPaste(true)}>
              paste the text
            </button>
            .
          </>
        )}
      </p>
      {problem && (
        <p className="sx-notice bad" role="alert">
          {problem}
        </p>
      )}
      {failed && (
        <p className="sx-notice warn" role="alert">
          {failed.message}
        </p>
      )}
      {create.isError && <ErrorNotice error={create.error} />}
      <div className="sx-row">
        <button type="submit" className="sx-btn" disabled={reading || tooLong}>
          {reading ? "Reading the posting…" : "Read the posting"}
        </button>
      </div>
    </form>
  );
}

function RoleSteps({ jobId, step, setStep }: { jobId: string; step: Step; setStep: (s: Step) => void }) {
  const job = useJob(jobId, false);
  const [edits, setEdits] = useState<Partial<JobPosting>>({});
  const [date, setDate] = useState("");
  if (!job.data?.posting) return <Loading label="Reading the posting" />;
  const posting = { ...job.data.posting, ...edits };
  if (step === 2) {
    return (
      <CheckStep
        posting={posting}
        curated={job.data.generic_mode === false}
        date={date}
        setDate={setDate}
        setEdits={(e) => setEdits((prev) => ({ ...prev, ...e }))}
        onBack={() => setStep(1)}
        onNext={() => setStep(3)}
      />
    );
  }
  return <InterviewsStep jobId={jobId} posting={posting} date={date} onBack={() => setStep(2)} />;
}

function CheckStep({
  posting,
  curated,
  date,
  setDate,
  setEdits,
  onBack,
  onNext,
}: {
  posting: JobPosting;
  curated: boolean;
  date: string;
  setDate: (d: string) => void;
  setEdits: (e: Partial<JobPosting>) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const ok = posting.company_name.trim() && posting.title.trim();
  return (
    <div className="sx-card">
      {curated && (
        <div className="sx-notice t">
          Strova has an interview profile for {posting.company_name} and will interview in its style.
        </div>
      )}
      <div className="sx-grid2">
        <div className="sx-field">
          <label htmlFor="co">Company</label>
          <input id="co" value={posting.company_name} onChange={(e) => setEdits({ company_name: e.target.value })} />
        </div>
        <div className="sx-field">
          <label htmlFor="ti">Job title</label>
          <input id="ti" value={posting.title} onChange={(e) => setEdits({ title: e.target.value })} />
        </div>
      </div>
      <div className="sx-grid2">
        <div className="sx-field">
          <label htmlFor="lv">Level</label>
          <select id="lv" value={posting.level ?? ""} onChange={(e) => setEdits({ level: (e.target.value || null) as Level | null })}>
            <option value="">Not stated</option>
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {levelLabel[l]}
              </option>
            ))}
          </select>
        </div>
        <div className="sx-field">
          <label htmlFor="dt">Interview date (optional)</label>
          <input id="dt" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>
      {posting.must_have_skills.length > 0 && (
        <div className="sx-field">
          <span style={{ fontWeight: 600, fontSize: 14 }}>Must-have skills</span>
          <div className="sx-chips">
            {posting.must_have_skills.map((s) => (
              <span key={s} className="sx-chip">
                {s}
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="sx-row">
        <button type="button" className="sx-btn" onClick={onNext} disabled={!ok}>
          Looks right
        </button>
        <button type="button" className="sx-btn quiet" onClick={onBack}>
          Back
        </button>
      </div>
    </div>
  );
}

function InterviewsStep({ jobId, posting, date, onBack }: { jobId: string; posting: JobPosting; date: string; onBack: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const suggested = useSuggestedInterviews(jobId);
  const resumes = useResumes();
  const live = (resumes.data ?? []).filter((r) => !r.deleted);
  const main = live.find((r) => r.is_main) ?? live[0];
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [chooseResume, setChooseResume] = useState(false);
  const [kept, setKept] = useState<Set<Kind> | null>(null);
  const chosen = live.find((r) => r.id === resumeId) ?? main;
  const keep = kept ?? new Set(suggested.data?.items.filter((i) => i.usual).map((i) => i.interview_type) ?? []);
  const create = useMutation({
    mutationFn: async () => {
      if (!chosen) throw new Error("Add a resume first.");
      const saved = await jobTargetsApi.update(jobId, {
        posting,
        interview_types: [...keep],
        resume_id: chosen.id,
      });
      if (date) await planApi.setInterviewDate(jobId, date);
      // The gap analysis for this role and resume runs in the background, as before.
      void gapApi.start(jobId, { resume_id: chosen.id, reuse_ready: true }).catch(() => undefined);
      return saved;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: roleKeys.roles });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate(rolePath(jobId));
    },
  });

  const toggle = (k: Kind) =>
    setKept(() => {
      const next = new Set(keep);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  return (
    <div className="sx-card coach">
      <div className="sx-row">
        <Strova mode="coaching" size={28} />
        <h2>Interviews Strova suggests for {posting.company_name}</h2>
      </div>
      <p className="sx-small sx-muted">
        {suggested.data?.company_mode === "curated"
          ? `From ${posting.company_name}'s usual interview rounds. Keep, remove or add types.`
          : "From a standard interview loop. Keep, remove or add types."}
      </p>
      {suggested.isPending && <Loading label="Strova is choosing the interviews" />}
      {suggested.isError && <ErrorNotice error={suggested.error} />}
      <div className="sx-stack">
        {suggested.data?.items.map((i) => (
          <label key={i.interview_type} className="sx-card tight" style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
            <input type="checkbox" checked={keep.has(i.interview_type)} onChange={() => toggle(i.interview_type)} />
            <span style={{ flex: 1 }}>
              <strong>{interviewTypeLabel[i.interview_type]}</strong>
              <br />
              <span className="sx-small sx-muted">
                {i.usual ? i.description : `Not usual at ${posting.company_name} for this role. ${i.description}`}
              </span>
            </span>
          </label>
        ))}
      </div>
      <div className="sx-between sx-small">
        <span>
          Measured against: <strong>{chosen ? `${chosen.name ?? "Resume"}${chosen.is_main ? " (main)" : ""}` : "no resume yet"}</strong>
        </span>
        {live.length > 1 && (
          <button type="button" className="sx-link" onClick={() => setChooseResume((v) => !v)}>
            Use another resume
          </button>
        )}
        {live.length <= 1 && <Link to="/resumes">Use another resume</Link>}
      </div>
      {chooseResume && (
        <div className="sx-field">
          <label htmlFor="role-resume">Resume for this role</label>
          <select id="role-resume" value={chosen?.id ?? ""} onChange={(e) => setResumeId(e.target.value)}>
            {live.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name ?? "Resume"}
                {r.is_main ? " (main)" : ""}
              </option>
            ))}
          </select>
        </div>
      )}
      {create.isError && <ErrorNotice error={create.error} />}
      <div className="sx-row">
        <button type="button" className="sx-btn" onClick={() => create.mutate()} disabled={create.isPending || keep.size === 0 || !chosen}>
          Create the role
        </button>
        <button type="button" className="sx-btn quiet" onClick={onBack}>
          Back
        </button>
      </div>
    </div>
  );
}
