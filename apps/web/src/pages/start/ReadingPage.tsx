/**
 * ON-2 (mockup #reading): Strova analysing while the extraction runs. Moves on by itself when the
 * resume is read; a refusal (IN-7) or a failure shows the reason and "Try another file".
 */
import { useEffect } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { useResume, useResumeTask } from "../../api/hooks";
import { jobProblem } from "../../api/inputs";
import { Strova } from "../../components/strova";
import "../../components/ux/ux.css";
import { readyPath, START } from "./paths";

export function ReadingPage() {
  const { resumeId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const task = useResumeTask(resumeId, params.get("task"));
  const problem = jobProblem(task.data);
  const resume = useResume(resumeId, problem === null);
  const read = resume.data?.status === "extracted" && !resume.data.deleted;

  useEffect(() => {
    if (read) navigate(readyPath(resumeId), { replace: true });
  }, [read, navigate, resumeId]);

  if (problem || resume.isError || resume.data?.deleted) {
    const message = problem?.message ?? "We could not read that resume.";
    return (
      <div className="sx-solo">
        <div className="sx-reading">
          <Strova mode="coaching" size={88} />
          <h1>Strova could not read that resume</h1>
          <p className="sx-notice warn" role="alert">
            {message}
          </p>
          <Link className="sx-btn" to={START}>
            Try another file
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="sx-solo">
      <div className="sx-reading" role="status" aria-live="polite">
        <Strova mode="analysing" size={160} />
        <h1>Strova is reading your resume</h1>
        <p className="sx-muted">
          Finding your roles, achievements, issues to fix and story ideas. This takes a few seconds.
        </p>
      </div>
    </div>
  );
}
