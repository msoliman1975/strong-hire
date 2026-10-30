/**
 * ON-6 (mockup #what-first): the two paths, prep and rehearse or build your stories, with the
 * "start anywhere" copy, and the two quiet links.
 */
import { Link } from "react-router";

import { useResumes, useStoryIdeas } from "../../api/hooks";
import { Strova } from "../../components/strova";
import "../../components/ux/ux.css";

export const ADD_ROLE_PATH = "/roles/new";
export const CRAFT_PATH = "/coach/new";

export function WhatFirstPage() {
  const resumes = useResumes();
  const main = resumes.data?.find((r) => !r.deleted && r.is_main) ?? resumes.data?.find((r) => !r.deleted) ?? null;
  const ideas = useStoryIdeas(main?.id ?? null);
  const strongest = ideas.data?.ideas[0];
  // Shorten at a word boundary, so the quote never ends mid-word.
  const short = (t: string) => (t.length > 40 ? `${t.slice(0, 39).replace(/\s+\S*$/, "").replace(/[,;:]$/, "")}…` : t);
  const craft = strongest
    ? `${CRAFT_PATH}?idea=${encodeURIComponent(strongest.resume_line_ref)}&resume=${main?.id ?? ""}`
    : CRAFT_PATH;

  return (
    <div className="sx-solo">
      <div className="sx-row" style={{ gap: 16 }}>
        <Strova mode="coaching" size={72} />
        <div className="sx-stack" style={{ gap: 6 }}>
          <div className="sx-eyebrow">You're all set</div>
          <h1>What would you like to do first?</h1>
          <p className="sx-muted" style={{ maxWidth: "62ch" }}>
            Your resume and your plan are ready, so you can start anywhere. There's no wrong first step: every path below
            feeds the others, and you can switch at any time from Home.
          </p>
        </div>
      </div>
      <div className="sx-grid2">
        <Link className="sx-choice t" to={ADD_ROLE_PATH}>
          <span className="sx-eyebrow teal">Prep and rehearse</span>
          <h2>I'm applying to a role</h2>
          <span className="sx-small">
            Add the job posting. Strova suggests the interviews to rehearse and measures them against your resume.
          </span>
          <span className="sx-small" style={{ color: "var(--sh-teal)", fontWeight: 600 }}>
            Add a target role
          </span>
        </Link>
        <Link className="sx-choice v" to={craft}>
          <span className="sx-eyebrow">Build your stories</span>
          <h2>Build my stories</h2>
          <span className="sx-small">
            {strongest
              ? `Start with your strongest idea, "${short(strongest.achievement)}". Strova asks the questions.`
              : "Start with one moment from your career. Strova asks the questions."}
          </span>
          <span className="sx-small" style={{ color: "var(--sh-violet-ink)", fontWeight: 600 }}>
            Craft a story with Strova
          </span>
        </Link>
      </div>
      <p className="sx-muted sx-small">
        Or <Link to={main ? `/resumes/${main.id}` : "/resumes"}>fix my resume first</Link>, or <Link to="/">go to Home</Link>.
      </p>
    </div>
  );
}
