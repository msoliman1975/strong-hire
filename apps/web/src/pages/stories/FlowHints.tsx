/**
 * SC-8, SC-9 (UI): Strova's advisory notes on a styled story. Flow flags (where the story does not
 * hang together) each offer Ask me about it (a short session with Strova on the story) and
 * Dismiss. Skill hints ("This story could also show …") offer Deepen (tags the skill and opens a
 * short session for it) and Not now. Neither changes the status.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { apiClient, unwrap } from "../../api/client";
import type { components } from "../../api/schema.gen";
import { Strova } from "../../components/strova";
import { ErrorNotice } from "../../components/ui";
import { competencyLabel } from "../../labels";
import { SECTION_LABEL, SLOT_LABEL } from "../coach/outline";
import { newCoachPath } from "../coach/paths";
import { storyKeys, type Competency, type Story } from "./api";

type S = components["schemas"];
export type FlowFlag = S["FlowFlag"];
export type SkillHint = S["SkillHint"];

const FLAG_LABEL: Record<S["FlowFlagType"], string> = {
  action_vs_problem: "The actions and the problem",
  result_vs_problem: "The result and the problem",
  number_conflict: "Two numbers disagree",
  timeline_conflict: "The timeline disagrees",
  loose_end: "A loose end",
};

const flowApi = {
  check: async (id: string) =>
    unwrap(await apiClient.POST("/stories/{story_id}/flow-check", { params: { path: { story_id: id } } })) as Story,
  dismissFlag: async (id: string, key: string) =>
    unwrap(
      await apiClient.POST("/stories/{story_id}/flow-flags/{key}/dismiss", { params: { path: { story_id: id, key } } }),
    ) as Story,
  deepen: async (id: string, skill: Competency) =>
    unwrap(
      await apiClient.POST("/stories/{story_id}/hints/{skill}/deepen", { params: { path: { story_id: id, skill } } }),
    ) as Story,
  dismissHint: async (id: string, skill: Competency) =>
    unwrap(
      await apiClient.POST("/stories/{story_id}/hints/{skill}/dismiss", { params: { path: { story_id: id, skill } } }),
    ) as Story,
};

const cites = (flag: FlowFlag) =>
  flag.slots
    .map((r) => `${SECTION_LABEL[r.section]}: ${(r.step ?? null) !== null ? `step ${(r.step as number) + 1}, ` : ""}${(SLOT_LABEL[r.slot] ?? r.slot).toLowerCase()}`)
    .join(" · ");

export function FlowHints({
  storyId,
  flags,
  hints,
  ready,
  onStory,
  showCheck = true,
}: {
  storyId: string;
  flags: FlowFlag[];
  hints: SkillHint[];
  ready: boolean;
  onStory?: (story: Story) => void;
  showCheck?: boolean;
}) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const saved = (story: Story) => {
    client.setQueryData(storyKeys.one(story.id), story);
    void client.invalidateQueries({ queryKey: storyKeys.all });
    onStory?.(story);
  };
  const check = useMutation({ mutationFn: () => flowApi.check(storyId), onSuccess: saved });
  const dismissFlag = useMutation({ mutationFn: (key: string) => flowApi.dismissFlag(storyId, key), onSuccess: saved });
  const deepen = useMutation({
    mutationFn: (skill: Competency) => flowApi.deepen(storyId, skill),
    onSuccess: (story, skill) => {
      saved(story);
      navigate(newCoachPath({ story: storyId, skill }));
    },
  });
  const notNow = useMutation({ mutationFn: (skill: Competency) => flowApi.dismissHint(storyId, skill), onSuccess: saved });
  const error = check.error ?? dismissFlag.error ?? deepen.error ?? notNow.error;
  if (!flags.length && !hints.length && !(showCheck && ready)) return null;
  return (
    <div className="sx-stack flow-hints">
      {(flags.length > 0 || (showCheck && ready)) && (
        <section className="sx-card tight coach" aria-labelledby={`flow-${storyId}`}>
          <div className="sx-row">
            <Strova mode="thinking" size={28} />
            <h2 id={`flow-${storyId}`} className="flow-hints__title">
              Does it hang together?
            </h2>
          </div>
          {flags.length === 0 ? (
            <span className="sx-small sx-muted">
              {check.isSuccess ? "Strova found nothing that doesn't fit." : "Strova can check that the parts of your story connect."}
            </span>
          ) : (
            <ul className="plain-list sx-stack" aria-label="Flow flags">
              {flags.map((f) => (
                <li key={f.key} className="flow-flag" data-testid="flow-flag" data-type={f.type}>
                  <span className="sx-eyebrow">{FLAG_LABEL[f.type]}</span>
                  <span>{f.question}</span>
                  <span className="sx-small sx-muted">{cites(f)}</span>
                  <div className="sx-row">
                    <button
                      type="button"
                      className="sx-btn sm"
                      onClick={() => navigate(newCoachPath({ story: storyId }))}
                      aria-label={`Ask me about it: ${f.question}`}
                    >
                      Ask me about it
                    </button>
                    <button
                      type="button"
                      className="sx-btn quiet sm"
                      disabled={dismissFlag.isPending}
                      onClick={() => dismissFlag.mutate(f.key)}
                      aria-label={`Dismiss: ${f.question}`}
                    >
                      Dismiss
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {showCheck && ready && (
            <div>
              <button type="button" className="sx-btn ghost sm" disabled={check.isPending} onClick={() => check.mutate()}>
                {check.isPending ? "Strova is checking" : flags.length ? "Check again" : "Check the flow"}
              </button>
            </div>
          )}
          <span className="sx-small sx-muted">Advisory only: these never change the story's status.</span>
        </section>
      )}
      {hints.length > 0 && (
        <section className="sx-card tight" aria-labelledby={`hints-${storyId}`}>
          <h2 id={`hints-${storyId}`} className="flow-hints__title">
            This story could also show
          </h2>
          <ul className="plain-list sx-stack" aria-label="Skill hints">
            {hints.map((h) => (
              <li key={h.skill} className="skill-hint" data-testid="skill-hint">
                <strong>{competencyLabel(h.skill)}</strong>
                <span className="sx-small">{h.reason}</span>
                <div className="sx-row">
                  <button
                    type="button"
                    className="sx-btn sm"
                    disabled={deepen.isPending}
                    onClick={() => deepen.mutate(h.skill)}
                    aria-label={`Deepen ${competencyLabel(h.skill)}`}
                  >
                    Deepen
                  </button>
                  <button
                    type="button"
                    className="sx-btn quiet sm"
                    disabled={notNow.isPending}
                    onClick={() => notNow.mutate(h.skill)}
                    aria-label={`Not now: ${competencyLabel(h.skill)}`}
                  >
                    Not now
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      {error && <ErrorNotice error={error} title="Strova could not do that" />}
    </div>
  );
}
