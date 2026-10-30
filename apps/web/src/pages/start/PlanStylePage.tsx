/**
 * ON-5 (mockup #plan-style): what the plan covers now (stories and resume, with rehearsals added
 * with a target role), then the two styles. Saves plan_style (PS-2) and goes to "What first".
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

import { accountApi } from "../../api/account";
import { useProfile, useResumeIssues, useResumes, useStoryIdeas } from "../../api/hooks";
import type { Profile } from "../../api/types";
import { ErrorNotice } from "../../components/ui";
import "../../components/ux/ux.css";
import { WHAT_FIRST } from "./paths";

type Style = NonNullable<Profile["plan_style"]>;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function Later() {
  return (
    <span className="sx-small sx-muted" style={{ borderTop: "1px dashed var(--sh-line-strong)", paddingTop: 6 }}>
      <span className="sx-chip">Rehearsals</span> Added when you add a target role
    </span>
  );
}

export function PlanStylePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const profile = useProfile();
  const resumes = useResumes();
  const main = resumes.data?.find((r) => !r.deleted && r.is_main) ?? resumes.data?.find((r) => !r.deleted) ?? null;
  const issues = useResumeIssues(main?.id ?? null);
  const ideas = useStoryIdeas(main?.id ?? null);
  const [style, setStyle] = useState<Style>(profile.data?.plan_style ?? "weekly");
  const save = useMutation({
    mutationFn: () => accountApi.savePlanSettings({ plan_style: style }),
    onSuccess: (saved) => {
      queryClient.setQueryData(["account", "profile"], saved);
      navigate(WHAT_FIRST);
    },
  });

  const ideaCount = ideas.data?.ideas.length ?? 0;
  const issueCount = issues.data?.open.length ?? 0;
  const firstIdea = ideas.data?.ideas[0]?.achievement;
  const weekly = style === "weekly";

  return (
    <div className="sx-solo">
      <div className="sx-stack" style={{ gap: 6 }}>
        <div className="sx-eyebrow">Your plan</div>
        <h1>How do you like to work?</h1>
        <p className="sx-muted" style={{ maxWidth: "62ch" }}>
          Strova keeps one plan for you. For now it covers completing your stories and fixing your resume findings.
          Pick the style that suits you.
        </p>
      </div>
      <div className="sx-card tight" style={{ gap: 10 }} data-testid="covers-now">
        <strong>What your plan covers now</strong>
        <div className="sx-grid3">
          <div className="sx-notice v sx-small">
            <span className="sx-chip v">Stories</span>
            <br />
            <strong>Complete your stories</strong>
            <br />
            {ideaCount > 0 ? `Start with the ${plural(ideaCount, "idea")} from your resume.` : "Craft your first story with Strova."}
          </div>
          <div className="sx-notice warn sx-small">
            <span className="sx-chip warn">Resume</span>
            <br />
            <strong>Fix your resume findings</strong>
            <br />
            {issueCount > 0 ? `${plural(issueCount, "issue")} to fix or accept.` : "Nothing to fix right now."}
          </div>
          <div className="sx-notice sx-small" style={{ background: "var(--sh-ground)", border: "1px dashed var(--sh-line-strong)" }}>
            <span className="sx-chip">Rehearsals</span>
            <br />
            <strong>Not yet</strong>
            <br />
            Mock interviews join your plan once you add a target role.
          </div>
        </div>
      </div>
      <PlanStyleChoices style={style} onChange={setStyle} examples={{ firstIdea, ideaCount, issueCount }} />
      <p className="sx-muted sx-small">
        Both styles cover the same work. When you add a target role, its mock interviews are added to whichever style
        you pick. You can change the style any time in your profile.
      </p>
      {save.isError && <ErrorNotice error={save.error} />}
      <div className="sx-row">
        <button type="button" className="sx-btn" onClick={() => save.mutate()} disabled={save.isPending}>
          Use the {weekly ? "weekly plan" : "checklist"}
        </button>
      </div>
    </div>
  );
}

/** PS-2: the two plan styles, each with an example of what it shows. Onboarding (ON-5) shows the
 * plan before a role; Profile passes `rehearsal` and `story` from the user's plan. */
export function PlanStyleChoices({
  style,
  onChange,
  examples,
}: {
  style: Style;
  onChange: (next: Style) => void;
  examples: { firstIdea?: string; ideaCount: number; issueCount: number; rehearsal?: string; story?: string };
}) {
  const { firstIdea, ideaCount, issueCount, rehearsal, story = "your next story" } = examples;
  const withRole = rehearsal !== undefined;
  const short = (t: string) => (t.length > 38 ? `${t.slice(0, 36).trimEnd()}…` : t);
  const weekly = style === "weekly";
  const setStyle = onChange;
  return (
    <div className="sx-grid2" role="group" aria-label="Plan style">
      <button type="button" className={`sx-choice${weekly ? " sel" : ""}`} aria-pressed={weekly} onClick={() => setStyle("weekly")}>
        <span className="sx-eyebrow">Weekly plan</span>
        <h2>Strova plans each week for you</h2>
        <span className="sx-small sx-muted">Good if you like a routine, or have an interview date.</span>
        <span className="sx-card tight" style={{ marginTop: 6 }}>
          {withRole ? (
            <>
              <span className="sx-small">
                <span className="sx-mono sx-muted">Mon</span> Take: {rehearsal}
              </span>
              <span className="sx-small">
                <span className="sx-mono sx-muted">Wed</span> Story goal: {story} to Ready
              </span>
              <span className="sx-small">
                <span className="sx-mono sx-muted">Fri</span> Fix one resume issue
              </span>
            </>
          ) : (
            <>
              <span className="sx-small">
                <span className="sx-mono sx-muted">Mon</span> Story goal: build{" "}
                {firstIdea ? `"${short(firstIdea)}"` : "your first story"}
              </span>
              <span className="sx-small">
                <span className="sx-mono sx-muted">Wed</span> Fix one resume issue
              </span>
              <span className="sx-small">
                <span className="sx-mono sx-muted">Fri</span> Story goal: get it to Ready
              </span>
              <Later />
            </>
          )}
        </span>
        <span className="sx-small sx-muted">
          Strova reminds you in the app and by email when something is due. You can mute email.
        </span>
      </button>
      <button type="button" className={`sx-choice${!weekly ? " sel" : ""}`} aria-pressed={!weekly} onClick={() => setStyle("checklist")}>
        <span className="sx-eyebrow">Readiness checklist</span>
        <h2>Work through a list at your own pace</h2>
        <span className="sx-small sx-muted">Good if your schedule changes week to week.</span>
        <span className="sx-card tight" style={{ marginTop: 6 }}>
          {withRole && (
            <span className="sx-small">
              <span className="sx-chip t">Rehearsals</span> {rehearsal} readiness 75 or more
            </span>
          )}
          <span className="sx-small">
            <span className="sx-chip v">Stories</span>{" "}
            {ideaCount > 0 ? `Build your ${plural(ideaCount, "story idea")} to Ready` : "Build your first story to Ready"}
          </span>
          <span className="sx-small">
            <span className="sx-chip warn">Resume</span>{" "}
            {issueCount > 0 ? `Fix or accept ${plural(issueCount, "resume issue")}` : "Keep your resume clean"}
          </span>
          {!withRole && <Later />}
        </span>
        <span className="sx-small sx-muted">No schedule and no reminders, just a clear list that ticks itself off.</span>
      </button>
    </div>
  );
}
