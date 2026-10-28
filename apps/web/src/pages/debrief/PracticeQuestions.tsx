import { Link } from "react-router";

import type { Competency, Debrief, Scorecard } from "../../api/types";
import { competencyLabel } from "../../labels";
import { questionsPath } from "../../paths";

/**
 * QB-4: the two or three competencies with the lowest scores, weakest first. The third is kept
 * only when it scored as low as the second.
 */
export function weakestCompetencies(scorecard: Scorecard | null): Competency[] {
  if (!scorecard) return [];
  const sorted = [...scorecard.competency_scores].sort((a, b) => a.score - b.score);
  const picked = sorted.slice(0, 2);
  if (sorted.length > 2 && sorted[2].score === sorted[1].score) picked.push(sorted[2]);
  return picked.map((c) => c.competency);
}

/** QB-4: the Questions page for this company (General when it is not curated), this interview
 * type and the weakest areas. A Custom session mixes types, so its link filters by area only. */
export function PracticeQuestions({ debrief }: { debrief: Debrief }) {
  const areas = weakestCompetencies(debrief.scorecard);
  const company = debrief.company_slug;
  const { config } = debrief.session;
  const to = questionsPath({
    company: company ?? "general",
    interviewType: config.custom ? null : config.interview_type,
    competencies: areas,
  });
  return (
    <section className="side-panel" aria-labelledby="practice-heading">
      <h2 id="practice-heading">Practice questions</h2>
      <p className="muted small">
        {company && debrief.company_name ? `${debrief.company_name} and common` : "Common"} questions
        {areas.length > 0 && ` for ${areas.map((a) => competencyLabel(a).toLowerCase()).join(", ")}`}, with
        hints on what each one looks for.
      </p>
      <Link className="btn btn--secondary" to={to}>
        Practice questions for your weak areas
      </Link>
    </section>
  );
}
