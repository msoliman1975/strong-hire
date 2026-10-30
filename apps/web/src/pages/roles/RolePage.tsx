/**
 * TG-4 (mockup #role): one target role. The interviews (each opens its interview page), what
 * they'll look for (skills, where they'll probe, must-haves the resume never shows), your stories
 * for this role (story fit, ST-5) and what you know about the interview (IN-4).
 */
import { Link, useParams } from "react-router";

import { useJob, useJobs, useResumeIssues, useResumes } from "../../api/hooks";
import { useRoleInterviews, useRoles } from "../../api/roles";
import type { InterviewWithReadiness } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { competencyLabel } from "../../labels";
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
          {match !== null && match !== undefined && (
            <span className="sx-mono" style={{ color: "var(--sh-ink)" }}>
              Match {match}
            </span>
          )}
          <span>
            {resumeLabel(resumes.data, resumeId)} · <Link to="/resumes">change</Link>
          </span>
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
      <section className="sx-card dashed" aria-labelledby="ctx-card-heading">
        <h2 id="ctx-card-heading">Know anything about this interview?</h2>
        <p className="sx-small sx-muted">
          {hasContext
            ? [job.data.stage, job.data.context.interviewer_role, job.data.context.concerns].filter(Boolean).join(" · ")
            : "The stage, the interviewer's role, recruiter notes, or what worries you. Optional, and Strova focuses on it."}
        </p>
        <div className="sx-row">
          <ContextDialog job={job.data} />
        </div>
      </section>
    </div>
  );
}
