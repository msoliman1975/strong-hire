/**
 * RM-1 (mockup #cvs): "{First name}'s Resumes". Every resume, the main one marked, each with its
 * open issues and story ideas. The user can make another resume main (RM-2).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { resumesApi } from "../../api/inputs";
import { useAuth, useResumeIssues, useResumes, useStoryIdeas } from "../../api/hooks";
import type { ResumeOut } from "../../api/types";
import { resumesLabel } from "../../components/Layout";
import { CvLibrary } from "../../components/LibrarySection";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { MAX_RESUME_MB, MAX_RESUMES, RESUMES_FULL } from "../../limits";
import { START } from "../start/paths";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export const resumePath = (id: string) => `/resumes/${id}`;

function ResumeRow({ resume }: { resume: ResumeOut }) {
  const ready = resume.status === "extracted";
  const issues = useResumeIssues(ready ? resume.id : null);
  const ideas = useStoryIdeas(ready ? resume.id : null);
  const queryClient = useQueryClient();
  const makeMain = useMutation({
    mutationFn: () => resumesApi.setMain(resume.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["resumes"] }),
  });
  const facts = !ready
    ? ["Still being read"]
    : [
        issues.data ? `${plural(issues.data.open.length, "issue")} open` : null,
        ideas.data ? plural(ideas.data.ideas.length, "story idea") : null,
      ].filter(Boolean);
  return (
    <div className="sx-list-row">
      <div className="sx-stack" style={{ gap: 2 }}>
        <strong>
          <Link className="sx-plain" to={resumePath(resume.id)}>
            {resume.name ?? "Resume"}
          </Link>{" "}
          {resume.is_main && <span className="sx-chip dark">Main</span>}
        </strong>
        <span className="sx-small sx-muted">{facts.join(" · ")}</span>
      </div>
      <span className="sx-row">
        {!resume.is_main && (
          <button type="button" className="sx-btn quiet sm" onClick={() => makeMain.mutate()} disabled={makeMain.isPending}>
            Make main
          </button>
        )}
        <Link className="sx-small sx-plain" to={resumePath(resume.id)} aria-label={`Open ${resume.name ?? "resume"}`}>
          Open
        </Link>
      </span>
    </div>
  );
}

export function ResumesListPage() {
  const auth = useAuth();
  const resumes = useResumes();
  const live = (resumes.data ?? []).filter((r) => !r.deleted);
  const full = live.length >= MAX_RESUMES;
  return (
    <div className="sx-page">
      <div className="sx-between">
        <h1>{resumesLabel(auth.data?.user?.full_name)}</h1>
        {full ? (
          <button type="button" className="sx-btn" disabled>
            Add a resume
          </button>
        ) : (
          <Link className="sx-btn" to={START}>
            Add a resume
          </Link>
        )}
      </div>
      <p className="sx-muted">
        Your main resume feeds your story ideas and is used for new target roles. Use other resumes for roles where you
        sent a different version.
      </p>
      {resumes.data && (
        <p className="sx-muted sx-small" data-testid="resume-limit">
          {live.length} of {MAX_RESUMES} · up to {MAX_RESUME_MB} MB each
        </p>
      )}
      {full && (
        <p className="sx-notice ground" role="status" data-testid="resumes-full">
          {RESUMES_FULL}
        </p>
      )}
      {resumes.isPending && <Loading label="Loading your resumes" />}
      {resumes.isError && <ErrorNotice error={resumes.error} />}
      {resumes.data && (
        <div className="sx-card">
          {live.length === 0 ? (
            <p className="sx-muted">No resume yet. Add one and Strova reads it.</p>
          ) : (
            live.map((r) => <ResumeRow key={r.id} resume={r} />)
          )}
        </div>
      )}
      {live.length > 0 && (
        <details className="sx-card sx-fold">
          <summary>
            <div className="sx-between">
              <h2>Rename or delete resumes</h2>
              <span className="caret" aria-hidden="true">
                ▾
              </span>
            </div>
          </summary>
          <CvLibrary />
        </details>
      )}
    </div>
  );
}
