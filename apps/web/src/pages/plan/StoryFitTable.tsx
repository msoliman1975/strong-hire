/**
 * ST-5: the story fit table on the plan page. For each skill the interview will test, the best
 * story and whether it is strong, thin or missing. The worker computes it; the page polls while
 * the API says `computing`. A missing story opens a coach session for that skill and this
 * interview (S31).
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { apiClient, unwrap } from "../../api/client";
import type { components } from "../../api/schema.gen";
import { Loading, Pill } from "../../components/ui";
import { competencyLabel } from "../../labels";
import { newCoachPath } from "../coach/paths";

export type StoryFitView = components["schemas"]["StoryFitView"];
export type StoryFitRow = components["schemas"]["StoryFitRow"];
type Strength = StoryFitRow["strength"];

/** The workbench (S21). */
export const storyPath = (id: string) => `/stories/${encodeURIComponent(id)}`;

const POLL_MS = 2000;

export const storyFitKey = (jobId: string, resumeId: string) => ["plan", jobId, resumeId, "story-fit"] as const;

export const useStoryFit = (jobId: string, resumeId: string) =>
  useQuery({
    queryKey: storyFitKey(jobId, resumeId),
    queryFn: async () =>
      unwrap(
        await apiClient.GET("/plan/{job_target_id}/{resume_id}/story-fit", {
          params: { path: { job_target_id: jobId, resume_id: resumeId } },
        }),
      ),
    refetchInterval: (query) => (query.state.data?.status === "computing" ? POLL_MS : false),
  });

const STRENGTH_LABEL: Record<Strength, string> = { strong: "Strong", thin: "Thin", missing: "Missing" };
const PILL_STATE: Record<Strength, "strong" | "thin" | "gap"> = { strong: "strong", thin: "thin", missing: "gap" };

export function StoryFitTable({ jobId, resumeId }: { jobId: string; resumeId: string }) {
  const fit = useStoryFit(jobId, resumeId);
  return (
    <section className="card" aria-labelledby="plan-story-fit-heading">
      <h2 id="plan-story-fit-heading">Your stories for this interview</h2>
      <p className="muted">For each skill they'll test, your best story and how well it shows that skill.</p>
      {fit.isPending ? (
        <Loading label="Matching your stories to the skills" />
      ) : fit.isError ? (
        <p className="muted">Story fit is not available right now.</p>
      ) : (
        <StoryFitBody view={fit.data} jobId={jobId} />
      )}
    </section>
  );
}

function StoryFitBody({ view, jobId }: { view: StoryFitView; jobId: string }) {
  if (view.rows.length === 0) return <Loading label="Matching your stories to the skills" />;
  return (
    <>
      <table className="plan-story-fit" data-testid="story-fit">
        <thead>
          <tr>
            <th scope="col">Skill</th>
            <th scope="col">Best story</th>
            <th scope="col">Fit</th>
          </tr>
        </thead>
        <tbody>
          {view.rows.map((r) => (
            <tr key={r.competency} data-strength={r.strength}>
              <th scope="row">{competencyLabel(r.competency)}</th>
              <td>
                {r.story ? (
                  <Link to={storyPath(r.story.id)}>{r.story.title}</Link>
                ) : (
                  <Link to={newCoachPath({ skill: r.competency, job: jobId })}>Build it with the coach</Link>
                )}
                <span className="muted small plan-story-fit__reason">{r.reason}</span>
              </td>
              <td>
                <Pill state={PILL_STATE[r.strength]}>{STRENGTH_LABEL[r.strength]}</Pill>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {view.status === "computing" && <p className="muted small">Still matching the other skills.</p>}
    </>
  );
}
