/**
 * ON-3 (mockup #cv-ready): what Strova read. Breakdown, Resume issues and Story ideas as cards,
 * collapsed by default with their counts visible, each with a link to where the user acts on it.
 */
import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

import { useResume, useResumeIssues, useStoryIdeas } from "../../api/hooks";
import type { Resume } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import "../../components/ux/ux.css";
import { competencyLabel } from "../../labels";
import { formatDate } from "../onboarding/resumeChecks";
import { breakdownPath, PLAN_STYLE } from "./paths";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The first sentence of the summary, as the mockup's one-line description. */
function firstSentence(summary: string | null | undefined): string | null {
  const t = summary?.trim();
  if (!t) return null;
  const m = /^(.+?[.!?])(\s|$)/.exec(t);
  return m ? m[1] : t;
}

export function Fold({
  eyebrow,
  eyebrowClass = "plain",
  title,
  children,
}: {
  eyebrow: string;
  eyebrowClass?: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <details className="sx-card sx-fold">
      <summary>
        <div className="sx-between">
          <div className="sx-stack" style={{ gap: 2 }}>
            <div className={`sx-eyebrow ${eyebrowClass}`}>{eyebrow}</div>
            <h2>{title}</h2>
          </div>
          <span className="sx-row sx-small" style={{ gap: 8 }}>
            Show
            <span className="caret" aria-hidden="true">
              ▾
            </span>
          </span>
        </div>
      </summary>
      {children}
    </details>
  );
}

export function BreakdownSummary({ resume }: { resume: Resume }) {
  return (
    <>
      {resume.roles.map((role, i) => (
        <div
          key={`${role.company}-${role.title}-${i}`}
          className="sx-stack"
          style={{ gap: 2, ...(i === 0 ? { borderTop: "1px solid var(--sh-line)", paddingTop: 10 } : {}) }}
        >
          <strong>
            {role.title} · {role.company}
          </strong>
          <span className="sx-small sx-muted">
            {role.start ? formatDate(role.start) : "Start not given"} to {role.end ? formatDate(role.end) : "now"}
          </span>
          {role.achievements
            .filter((a) => a.trim())
            .map((a) => (
              <span key={a} className="sx-small">
                · {a}
              </span>
            ))}
        </div>
      ))}
      {resume.skills.length > 0 && (
        <div className="sx-chips">
          {resume.skills.map((s) => (
            <span key={s} className="sx-chip">
              {s}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

export function ResumeReadyPage() {
  const { resumeId = "" } = useParams();
  const record = useResume(resumeId);
  const issues = useResumeIssues(resumeId);
  const ideas = useStoryIdeas(resumeId);
  const resume = record.data?.resume;

  if (record.isError) return <ErrorNotice error={record.error} />;
  if (!resume || !record.data) return <Loading label="Loading your resume" />;

  const achievements = resume.roles.reduce((n, r) => n + r.achievements.filter((a) => a.trim()).length, 0);
  const open = issues.data?.open ?? [];
  const ideaList = ideas.data?.ideas ?? [];
  const line = [record.data.name, firstSentence(resume.summary)].filter(Boolean).join(" · ");

  return (
    <div className="sx-solo">
      <div className="sx-row">
        <Strova mode="coaching" size={88} />
        <div className="sx-stack" style={{ gap: 4 }}>
          <div className="sx-eyebrow">Strova read your resume</div>
          <h1>Here is what your resume shows</h1>
          {line && <p className="sx-muted">{line}</p>}
        </div>
      </div>
      <div className="sx-stack">
        <Fold
          eyebrow="Breakdown"
          title={`${plural(resume.roles.length, "role")} · ${plural(achievements, "achievement")} · ${plural(resume.skills.length, "skill")}`}
        >
          <BreakdownSummary resume={resume} />
          <div className="sx-between">
            <span className="sx-small sx-muted">Edit any part on the full breakdown.</span>
            <Link className="sx-btn ghost sm" to={breakdownPath(resumeId)}>
              Open breakdown and issues
            </Link>
          </div>
        </Fold>
        <Fold
          eyebrow="Resume issues"
          eyebrowClass="warn"
          title={issues.isPending ? "Checking…" : open.length === 0 ? "Nothing to fix" : `${open.length} to look at`}
        >
          {issues.isError && <ErrorNotice error={issues.error} />}
          {open.map((issue) => (
            <div key={issue.key} className={`sx-notice sx-small ${issue.severity === "high" || issue.severity === "medium" ? "warn" : "ground"}`}>
              <strong style={issue.severity === "low" ? undefined : { color: "var(--sh-warn-ink)" }}>{issue.title}.</strong>{" "}
              {issue.detail}
            </div>
          ))}
          <div className="sx-between">
            <span className="sx-small sx-muted">Fix or accept each one now, or later from your plan.</span>
            <Link className="sx-btn ghost sm" to={breakdownPath(resumeId)}>
              Open breakdown and issues
            </Link>
          </div>
        </Fold>
        <Fold eyebrow="Story ideas" eyebrowClass="" title={ideas.isPending ? "Looking…" : plural(ideaList.length, "idea")}>
          {ideas.isError && <ErrorNotice error={ideas.error} />}
          {ideaList.map((idea) => (
            <div key={idea.resume_line_ref} className="sx-card tight">
              <strong>{idea.achievement}</strong>
              {idea.skills.length > 0 && (
                <span className="sx-chips">
                  {idea.skills.map((s) => (
                    <span key={s} className="sx-chip v">
                      {competencyLabel(s)}
                    </span>
                  ))}
                </span>
              )}
            </div>
          ))}
          <div className="sx-between">
            <span className="sx-small sx-muted">Build or dismiss each idea on your stories page.</span>
            <Link className="sx-btn ghost sm" to="/stories">
              Open Career Stories
            </Link>
          </div>
        </Fold>
      </div>
      <div className="sx-notice v">
        <strong>One more question, then you're in.</strong> Strova will plan your practice and your story work. Choose
        how you like to work.
      </div>
      <div className="sx-row">
        <Link className="sx-btn" to={PLAN_STYLE}>
          Continue
        </Link>
      </div>
    </div>
  );
}
