/**
 * RM-3 (mockup #cv): one resume. The breakdown with Edit and the resume issues with fix and accept
 * come first; then Strova's story ideas from it (Craft with Strova, Not a story, and the
 * achievements a story already tells), closed by default with their counts in the header. Resume-line suggestions from stories (SG-6) join this page with U08.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link, useParams } from "react-router";

import { resumesApi } from "../../api/inputs";
import { useResume, useResumeIssues, useStoryIdeas } from "../../api/hooks";
import { useRoles } from "../../api/roles";
import { suggestionKeys, suggestionsApi, useSuggestions } from "../../api/suggestions";
import type { Suggestion } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { competencyLabel } from "../../labels";
import { resumeCheckPath } from "../../paths";
import { rolePath, roleTitle } from "../roles/shared";
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

/** RM-3: the closed Story ideas header's summary, such as "3 ideas · 1 already a story". */
export function ideaCounts(open: number, used: number): string {
  const ideas = `${open} ${open === 1 ? "idea" : "ideas"}`;
  return used > 0 ? `${ideas} · ${used} already a story` : ideas;
}

/** Craft with Strova, seeded with this achievement (U10 reads `idea` and `resume`). */
export const craftFromIdeaPath = (resumeId: string, ref: string) =>
  `/coach/new?resume=${encodeURIComponent(resumeId)}&idea=${encodeURIComponent(ref)}`;

export function ResumeDetailPage() {
  const { resumeId = "" } = useParams();
  const queryClient = useQueryClient();
  const record = useResume(resumeId);
  const issues = useResumeIssues(resumeId);
  const ideas = useStoryIdeas(resumeId);
  const roles = useRoles();
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
  const usedBy = (roles.data ?? []).filter(
    (r) => !r.role.archived && r.interviews.some((i) => i.interview.resume_id === resumeId),
  );

  return (
    <div className="sx-page sx-page--wide">
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
            {usedBy.length > 0 && (
              <span>
                Used by{" "}
                {usedBy.map((r, n) => (
                  <Fragment key={r.role.id}>
                    {n > 0 && (n === usedBy.length - 1 ? " and " : ", ")}
                    <Link to={rolePath(r.role.id)}>{roleTitle(r.role)}</Link>
                  </Fragment>
                ))}
              </span>
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
              <ResumeLineSuggestions resumeId={resumeId} />
            </div>
          </div>
          <details className="sx-card coach sx-fold" data-testid="resume-ideas" aria-labelledby="ideas-heading">
            <summary className="sx-stack" style={{ gap: 6 }}>
              <div className="sx-between">
                <div className="sx-row">
                  <Strova mode="coaching" size={28} />
                  <h2 id="ideas-heading">Story ideas from this resume</h2>
                </div>
                <div className="sx-row">
                  <span className="sx-small sx-muted" data-testid="ideas-counts">
                    {ideaCounts(ideas.data?.ideas.length ?? 0, ideas.data?.used.length ?? 0)}
                  </span>
                  <span className="caret" aria-hidden="true">
                    ▾
                  </span>
                </div>
              </div>
              <p className="sx-small sx-muted">
                Strova's findings: she read your achievements and picked the ones that could become stories you tell in
                interviews.
              </p>
            </summary>
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
          </details>
        </>
      )}
    </div>
  );
}

/**
 * SG-6 on the resume page (mockup #cv): Strova's rewrites of a resume line from a story's result,
 * with Add to resume (then Undo) and Dismiss. Story ideas are shown above, from their own endpoint.
 */
function ResumeLineSuggestions({ resumeId }: { resumeId: string }) {
  const list = useSuggestions("resume", { resume_id: resumeId });
  const lines = (list.data ?? []).filter((s) => s.kind === "improve_resume_line");
  if (lines.length === 0) return null;
  return (
    <>
      {lines.map((s) => (
        <ResumeLineCard key={s.id} suggestion={s} resumeId={resumeId} />
      ))}
    </>
  );
}

function ResumeLineCard({ suggestion, resumeId }: { suggestion: Suggestion; resumeId: string }) {
  const client = useQueryClient();
  const [added, setAdded] = useState(false);
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["resumes"] });
    void client.invalidateQueries({ queryKey: suggestionKeys.place("resume", resumeId) });
  };
  const accept = useMutation({
    mutationFn: () => suggestionsApi.accept(suggestion.id),
    onSuccess: () => {
      setAdded(true);
      void client.invalidateQueries({ queryKey: ["resumes"] });
    },
  });
  const undo = useMutation({
    mutationFn: () => suggestionsApi.undo(suggestion.id),
    onSuccess: () => {
      setAdded(false);
      void client.invalidateQueries({ queryKey: ["resumes"] });
    },
  });
  const dismiss = useMutation({ mutationFn: () => suggestionsApi.dismiss(suggestion.id), onSuccess: refresh });
  const error = accept.error ?? undo.error ?? dismiss.error;
  const busy = accept.isPending || undo.isPending || dismiss.isPending;
  const p = suggestion.payload;
  if (p.kind !== "improve_resume_line") return null;
  return (
    <section className="sx-card coach" aria-label="Strova suggests a resume line" data-testid="resume-line-suggestion">
      <span className="sx-eyebrow">Strova suggests · from your stories</span>
      {added ? (
        <div className="sx-notice ok sx-small" role="status">
          <strong>Added to your resume.</strong>{" "}
          <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => undo.mutate()}>
            Undo
          </button>
        </div>
      ) : (
        <>
          <span className="sx-small">{suggestion.reason}</span>
          <div className="sx-diff">
            <del>{p.before}</del>
            <br />
            <ins>{p.after}</ins>
          </div>
          <div className="sx-row">
            <button type="button" className="sx-btn sm" disabled={busy} onClick={() => accept.mutate()}>
              Add to resume
            </button>
            <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => dismiss.mutate()}>
              Dismiss
            </button>
          </div>
        </>
      )}
      {error && (
        <span className="sx-small" role="alert">
          {error.message}
        </span>
      )}
    </section>
  );
}
