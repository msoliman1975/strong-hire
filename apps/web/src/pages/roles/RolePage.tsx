/**
 * TG-4 (mockup #role): one target role. The interviews (each opens its interview page), what
 * they'll look for (skills, where they'll probe, must-haves the resume never shows), your stories
 * for this role (story fit, ST-5) and what you know about the interview (IN-4).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useJob, useJobs, useResumeIssues, useResumes } from "../../api/hooks";
import { jobTargetsApi } from "../../api/inputs";
import { useRoleInterviews, useRoles } from "../../api/roles";
import type { InterviewWithReadiness, JobPosting } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { betaRoleFamilies, competencyLabel, roleFamilyLabel } from "../../labels";
import { newCoachPath } from "../coach/paths";
import { usePlan } from "../plan/api";
import { storyPath, useStoryFit } from "../plan/StoryFitTable";
import { resumePath } from "../resumes/ResumesListPage";
import { ContextDialog } from "./ContextDialog";
import { dateChip, interviewPath, resumeLabel, rolesPath, takesMeta, typeName } from "./shared";

function InterviewCard({ item, first }: { item: InterviewWithReadiness; first: boolean }) {
  const score = item.readiness.score;
  return (
    <Link className="sx-card tight" to={interviewPath(item.interview.id)} style={{ textDecoration: "none", color: "inherit" }}>
      <strong>{typeName(item.interview)}</strong>
      <div className="sx-between">
        <span className={`sx-score${score === null ? " sx-muted" : ""}`}>{score ?? "–"}</span>
        <span className="sx-small sx-muted">goal {item.readiness.goal}</span>
      </div>
      <div className="sx-bar">
        <span style={{ width: `${score ?? 0}%` }} />
      </div>
      <span className="sx-small sx-muted">{takesMeta(item)}</span>
      <span className={`sx-btn sm${first ? "" : " ghost"}`} style={{ marginTop: 6 }}>
        {item.takes_count === 0 ? "Start a take" : "Retake"}
      </span>
    </Link>
  );
}

/** TG-4: what Strova read from the job posting, in a dialog opened from the page's actions. */
export function PostingDialog({ posting, sourceUrl }: { posting: JobPosting; sourceUrl: string | null }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const n = posting.responsibilities.length;
  const meta = [posting.level_label, posting.team, posting.location].filter(Boolean).join(" · ");
  const counts = `${n} ${n === 1 ? "responsibility" : "responsibilities"} · ${posting.must_have_skills.length} must-have skills`;
  return (
    <>
      <button type="button" className="sx-btn ghost sm" onClick={() => dialog.current?.showModal()}>
        Job posting
      </button>
      <dialog ref={dialog} aria-labelledby="posting-heading" className="sx-dialog" data-testid="posting-dialog">
        <div className="sx-card">
          <div className="sx-stack" style={{ gap: 4 }}>
            <h2 id="posting-heading">The job posting</h2>
            <span className="sx-small sx-muted">{meta ? `${meta} · ${counts}` : counts}</span>
          </div>
          {n > 0 ? (
            <div className="sx-stack" style={{ gap: 6 }}>
              <h3>What you'll do</h3>
              <ul className="sx-small" style={{ margin: 0, paddingLeft: 18 }}>
                {posting.responsibilities.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="sx-notice warn sx-small">
              Strova found no responsibilities in this posting. If the link showed only part of it, add the role again and
              paste the job description instead.
            </p>
          )}
          {posting.must_have_skills.length > 0 && (
            <div className="sx-stack" style={{ gap: 6 }}>
              <h3>Must-have skills</h3>
              <div className="sx-chips">
                {posting.must_have_skills.map((k) => (
                  <span key={k} className="sx-chip">
                    {k}
                  </span>
                ))}
              </div>
            </div>
          )}
          {posting.nice_to_have_skills.length > 0 && (
            <div className="sx-stack" style={{ gap: 6 }}>
              <h3>Nice to have</h3>
              <div className="sx-chips">
                {posting.nice_to_have_skills.map((k) => (
                  <span key={k} className="sx-chip">
                    {k}
                  </span>
                ))}
              </div>
            </div>
          )}
          <div className="sx-between">
            {sourceUrl ? (
              <a className="sx-small" href={sourceUrl} target="_blank" rel="noreferrer">
                Open the original posting
              </a>
            ) : (
              <span />
            )}
            <button type="button" className="sx-btn sm" onClick={() => dialog.current?.close()}>
              Close
            </button>
          </div>
        </div>
      </dialog>
    </>
  );
}

/**
 * LB-2 in the page's actions: a role nothing uses yet (no gap report, no takes) can be deleted,
 * after a confirm; one with a gap report or takes is archived instead, so its reports keep their
 * role. A 409 from the server (a report made since the page loaded) switches to archive.
 */
export function RemoveRole({ jobId, inUse }: { jobId: string; inUse: boolean }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const dialog = useRef<HTMLDialogElement>(null);
  const [archiveOnly, setArchiveOnly] = useState(false);
  const done = () => {
    dialog.current?.close();
    // Roles, rehearsals, the plan and Home all list this role.
    void client.invalidateQueries();
    navigate(rolesPath);
  };
  const remove = useMutation({
    mutationFn: () => jobTargetsApi.remove(jobId),
    onSuccess: done,
    onError: (err) => {
      if ((err as { status?: number }).status === 409) setArchiveOnly(true);
    },
  });
  const archive = useMutation({ mutationFn: () => jobTargetsApi.archive(jobId), onSuccess: done });
  const keep = inUse || archiveOnly;
  const label = keep ? "Archive role" : "Delete role";
  const error = archiveOnly ? archive.error : (remove.error ?? archive.error);
  return (
    <>
      <button type="button" className="sx-btn quiet sm" onClick={() => dialog.current?.showModal()}>
        {label}
      </button>
      <dialog ref={dialog} aria-labelledby="remove-heading" className="sx-dialog" data-testid="remove-role">
        <div className="sx-card">
          <h2 id="remove-heading">{keep ? "Archive this role?" : "Delete this role?"}</h2>
          <p className="sx-small sx-muted">
            {keep
              ? "This role has a gap report or takes, so it can't be deleted. Archiving hides it from your roles; its reports stay."
              : "Nothing uses this role yet: no gap report and no takes. Deleting removes the job posting and its interviews. This can't be undone."}
          </p>
          {error && <ErrorNotice error={error} />}
          <div className="sx-row">
            <button
              type="button"
              className="sx-btn sm"
              disabled={remove.isPending || archive.isPending}
              onClick={() => (keep ? archive.mutate() : remove.mutate())}
            >
              {label}
            </button>
            <button type="button" className="sx-btn quiet sm" onClick={() => dialog.current?.close()}>
              Cancel
            </button>
          </div>
        </div>
      </dialog>
    </>
  );
}

const STRENGTH = { strong: { label: "Strong", cls: "ok" }, thin: { label: "Thin", cls: "warn" }, missing: { label: "Missing", cls: "bad" } } as const;

export function RolePage() {
  const { jobId = "" } = useParams();
  const roles = useRoles();
  const interviews = useRoleInterviews(jobId);
  const job = useJob(jobId, false);
  const jobs = useJobs();
  const resumes = useResumes();
  const summary = roles.data?.find((r) => r.role.id === jobId)?.role;
  const resumeId = interviews.data?.[0]?.interview.resume_id ?? resumes.data?.find((r) => r.is_main)?.id ?? "";
  const plan = usePlan(jobId, resumeId);
  const issues = useResumeIssues(resumeId || null, jobId);
  const fit = useStoryFit(jobId, resumeId);

  if (job.isError) return <ErrorNotice error={job.error} />;
  if (!job.data || !summary) return <Loading label="Loading the role" />;
  const posting = job.data.posting;
  const company = summary.company_name ?? posting?.company_name ?? null;
  const title = posting?.title ?? summary.name ?? "Target role";
  const chip = dateChip(summary, job.data.stage);
  const match = jobs.data?.find((j) => j.job_target.id === jobId)?.match_score;
  const kept = new Set(interviews.data?.map((i) => i.interview.interview_type));
  const tested = plan.data?.tested.filter((t) => kept.has(t.interview_type)) ?? [];
  // The most weighted skills across the kept interviews (each type's list is sorted by weight).
  const ranked = tested.flatMap((t) => t.competencies).sort((a, b) => b.share - a.share);
  const skills = [...new Set(ranked.map((c) => c.competency))].slice(0, 6);
  const gap = plan.data?.gap;
  const probes = gap?.status === "ready" ? (gap.analysis?.probe_areas ?? []) : [];
  const mustHave = issues.data?.open.find((i) => i.key.startsWith("job.must-have"));
  const hasContext = Boolean(job.data.stage || Object.values(job.data.context).some(Boolean));

  return (
    <div className="sx-page">
      <div className="sx-between" style={{ alignItems: "flex-start" }}>
        <div className="sx-stack" style={{ gap: 6 }}>
          <Link className="sx-small" to={rolesPath}>
            Target roles
          </Link>
          <div className="sx-eyebrow teal">Target role</div>
          <h1>
            {title}
            {company ? ` · ${company}` : ""}
          </h1>
          <div className="sx-row sx-small sx-muted">
            <span className={`sx-chip${chip.teal ? " t" : ""}`}>{chip.text}</span>
            {posting && betaRoleFamilies.has(posting.role_family) && (
              <span
                className="sx-chip v"
                title="Practice for this job category is new. Its questions and scoring are still being calibrated."
              >
                Beta: {roleFamilyLabel[posting.role_family]}
              </span>
            )}
            {match !== null && match !== undefined && (
              <span className="sx-mono" style={{ color: "var(--sh-ink)" }}>
                Match {match}
              </span>
            )}
            <span>
              {resumeLabel(resumes.data, resumeId)} · <Link to="/resumes">change</Link>
            </span>
          </div>
          {hasContext && (
            <p className="sx-small sx-muted" data-testid="role-context">
              You know: {[job.data.stage, job.data.context.interviewer_role, job.data.context.concerns].filter(Boolean).join(" · ")}
            </p>
          )}
        </div>
        {/* The role's actions sit at the top, where they are seen: posting, what you know, remove. */}
        <div className="sx-row" role="group" aria-label="Role actions">
          {posting && <PostingDialog posting={posting} sourceUrl={job.data.source_url} />}
          <ContextDialog job={job.data} />
          <RemoveRole
            jobId={jobId}
            inUse={Boolean(plan.data?.gap) || (interviews.data ?? []).some((i) => i.takes_count > 0)}
          />
        </div>
      </div>
      <section className="sx-card" aria-labelledby="ivs-heading">
        <div className="sx-between">
          <h2 id="ivs-heading">Interviews for this role</h2>
          <span className="sx-small sx-muted">Readiness is a practice estimate from Realistic takes</span>
        </div>
        {interviews.isError && <ErrorNotice error={interviews.error} />}
        {interviews.data?.length === 0 && <p className="sx-small sx-muted">No interviews kept for this role yet.</p>}
        <div className="sx-grid3">
          {interviews.data?.map((i, n) => (
            <InterviewCard key={i.interview.id} item={i} first={n === 0} />
          ))}
        </div>
      </section>
      <div className="sx-grid2">
        <section className="sx-card" aria-labelledby="look-heading">
          <h2 id="look-heading">What they'll look for</h2>
          {skills.length > 0 && (
            <div className="sx-chips">
              {skills.map((s) => (
                <span key={s} className="sx-chip">
                  {competencyLabel(s)}
                </span>
              ))}
            </div>
          )}
          {probes.length > 0 && (
            <p className="sx-small">
              <strong>Where they'll probe:</strong> {probes.join(", ")}.
            </p>
          )}
          {mustHave && (
            <div className="sx-notice warn sx-small">
              <strong style={{ color: "var(--sh-warn-ink)" }}>Must-haves your resume never shows:</strong> {mustHave.detail}.{" "}
              <Link to={resumePath(resumeId)}>Open your resume</Link>
            </div>
          )}
          {/* GA-1, GA-2: the full gap report (match score, strengths, gaps) for this role. */}
          <Link className="sx-small" to={`/jobs/${jobId}/gap-report`}>
            See the full gap report
          </Link>
        </section>
        <section className="sx-card coach" aria-labelledby="stories-heading">
          <div className="sx-row">
            <Strova mode="coaching" size={24} />
            <h2 id="stories-heading">Your stories for this role</h2>
          </div>
          {fit.isPending && <Loading label="Matching your stories to the skills" />}
          {fit.data?.rows.map((row) => {
            const s = STRENGTH[row.strength];
            return (
              <div key={row.competency} className="sx-list-row">
                <div className="sx-stack" style={{ gap: 3 }}>
                  <span className="sx-small sx-muted">{competencyLabel(row.competency)}</span>
                  {row.story ? (
                    <Link to={storyPath(row.story.id)}>
                      <strong>{row.story.title}</strong>
                    </Link>
                  ) : (
                    <>
                      <span className="sx-small sx-muted">None of your stories shows this yet.</span>
                      <Link className="sx-small" to={newCoachPath({ skill: row.competency, job: jobId })}>
                        <strong>Craft it with Strova</strong>
                      </Link>
                    </>
                  )}
                  {row.story && row.strength !== "strong" && <span className="sx-small sx-muted">{row.reason}</span>}
                </div>
                <span className={`sx-chip ${row.story?.status === "proven" ? "ok" : s.cls}`}>
                  {row.story?.status === "proven" ? "Proven" : s.label}
                </span>
              </div>
            );
          })}
        </section>
      </div>
    </div>
  );
}
