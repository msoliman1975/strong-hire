/**
 * RM-3 (mockup #cv): one resume. Story ideas from it (Craft with Strova, Not a story, and the
 * achievements a story already tells), the breakdown with Edit, and the resume issues with fix and
 * accept. Resume-line suggestions from stories (SG-6) join this page with U08.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { resumesApi } from "../../api/inputs";
import { useResume, useResumeIssues, useStoryIdeas } from "../../api/hooks";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { competencyLabel } from "../../labels";
import { resumeCheckPath } from "../../paths";
import { storyPath } from "../stories/paths";
import { BreakdownSummary } from "../start/ResumeReadyPage";
import { IssueList } from "./IssueList";
import { START } from "../start/paths";

const PART: Record<string, string> = {
  context: "context",
  stakes: "stakes",
  action: "your action",
  result: "result",
  reflection: "reflection",
};

/** Craft with Strova, seeded with this achievement (U10 reads `idea` and `resume`). */
export const craftFromIdeaPath = (resumeId: string, ref: string) =>
  `/coach/new?resume=${encodeURIComponent(resumeId)}&idea=${encodeURIComponent(ref)}`;

export function ResumeDetailPage() {
  const { resumeId = "" } = useParams();
  const queryClient = useQueryClient();
  const record = useResume(resumeId);
  const issues = useResumeIssues(resumeId);
  const ideas = useStoryIdeas(resumeId);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["resumes"] });
  };
  const makeMain = useMutation({ mutationFn: () => resumesApi.setMain(resumeId), onSuccess: refresh });
  const dismiss = useMutation({
    mutationFn: (ref: string) => resumesApi.dismissIdea(resumeId, ref),
    onSuccess: refresh,
  });

  if (record.isError) return <ErrorNotice error={record.error} />;
  if (!record.data) return <Loading label="Loading your resume" />;
  const resume = record.data.resume;
  const open = issues.data?.open ?? [];

  return (
    <div className="sx-page">
      <div className="sx-between">
        <div className="sx-stack" style={{ gap: 6 }}>
          <h1>{record.data.name ?? "Resume"}</h1>
          <div className="sx-row sx-small sx-muted">
            {record.data.is_main ? (
              <span className="sx-chip dark">Main resume</span>
            ) : (
              <button type="button" className="sx-btn quiet sm" onClick={() => makeMain.mutate()} disabled={makeMain.isPending}>
                Make this my main resume
              </button>
            )}
          </div>
        </div>
        <Link className="sx-btn ghost" to={START}>
          Upload a new version
        </Link>
      </div>
      {!resume && <Loading label="Strova is reading this resume" />}
      {resume && (
        <>
          <section className="sx-card coach" aria-labelledby="ideas-heading">
            <div className="sx-between">
              <div className="sx-row">
                <Strova mode="coaching" size={28} />
                <h2 id="ideas-heading">Story ideas from this resume</h2>
              </div>
              <span className="sx-muted sx-small">Strova found these in your achievements</span>
            </div>
            {ideas.isError && <ErrorNotice error={ideas.error} />}
            {dismiss.isError && <ErrorNotice error={dismiss.error} />}
            {ideas.data?.ideas.length === 0 && ideas.data.used.length === 0 && (
              <p className="sx-muted sx-small">No ideas left. Every achievement is a story or was set aside.</p>
            )}
            {ideas.data?.ideas.map((idea) => (
              <div key={idea.resume_line_ref} className="sx-card tight sx-sugg">
                <div className="txt">
                  <strong>{idea.achievement}</strong>
                  <span className="sx-chips">
                    {idea.skills.map((s) => (
                      <span key={s} className="sx-chip v">
                        {competencyLabel(s)}
                      </span>
                    ))}
                    <span className="sx-small sx-muted">
                      Still needs: {idea.missing_parts.map((p) => PART[p] ?? p).join(", ")}
                    </span>
                  </span>
                </div>
                <div className="sx-row">
                  <Link className="sx-btn sm" to={craftFromIdeaPath(resumeId, idea.resume_line_ref)}>
                    Craft with Strova
                  </Link>
                  <button
                    type="button"
                    className="sx-btn quiet sm"
                    onClick={() => dismiss.mutate(idea.resume_line_ref)}
                    disabled={dismiss.isPending}
                  >
                    Not a story
                  </button>
                </div>
              </div>
            ))}
            {ideas.data?.used.map((u) => (
              <div key={u.resume_line_ref} className="sx-between sx-notice ground">
                <span className="sx-muted">{u.achievement}</span>
                <Link to={storyPath(u.story_id)} className="sx-small" style={{ color: "var(--sh-ok-ink)", fontWeight: 600 }}>
                  Story: {u.story_title}
                </Link>
              </div>
            ))}
          </section>
          <div className="sx-grid2">
            <section className="sx-card" aria-labelledby="breakdown-heading">
              <div className="sx-between">
                <h2 id="breakdown-heading">Breakdown</h2>
                <Link className="sx-btn quiet sm" to={resumeCheckPath(resumeId)}>
                  Edit
                </Link>
              </div>
              {resume.summary && <p className="sx-small sx-muted">{resume.summary}</p>}
              <BreakdownSummary resume={resume} />
            </section>
            <div className="sx-stack" style={{ gap: 16 }}>
              <section className="sx-card" aria-labelledby="issues-heading">
                <div className="sx-between">
                  <h2 id="issues-heading">Resume issues</h2>
                  <span className="sx-small sx-muted">{issues.data ? `${open.length} open` : ""}</span>
                </div>
                {issues.isError && <ErrorNotice error={issues.error} />}
                {issues.data && open.length === 0 && <p className="sx-muted sx-small">Nothing to fix. Your resume reads well.</p>}
                <IssueList resumeId={resumeId} issues={open} compactActions />
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
