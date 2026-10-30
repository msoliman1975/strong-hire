/**
 * PS-2 (mockup #profile): Profile with Strova, when `v2_enabled` is on. Your plan style (the two
 * styles, saved at once), reminders from Strova (in the app always on; by email Mute or Unmute,
 * saving plan_email_muted, PS-6), the account summary, and your details (AC-3). Billing, export
 * and delete stay on Account.
 */
import "../components/ux/ux.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { accountApi } from "../api/account";
import { keys, useAuth, useProfile } from "../api/hooks";
import { personalPlanKey, usePersonalPlan } from "../api/personalPlan";
import type { Profile } from "../api/types";
import { ProfileForm } from "../components/ProfileForm";
import { ErrorNotice, Loading } from "../components/ui";
import { levelLabel } from "../labels";
import { PlanStyleChoices } from "./start/PlanStylePage";

type Style = NonNullable<Profile["plan_style"]>;

export function ProfileV2({
  saving,
  saveError,
  saved,
  onSave,
}: {
  saving: boolean;
  saveError: Error | null;
  saved: boolean;
  onSave: (body: Parameters<typeof accountApi.saveProfile>[0]) => void;
}) {
  const profile = useProfile();
  const auth = useAuth();
  const plan = usePersonalPlan();
  const client = useQueryClient();
  const settings = useMutation({
    mutationFn: (body: { plan_style?: Style; plan_email_muted?: boolean }) => accountApi.savePlanSettings(body),
    onSuccess: (next) => {
      client.setQueryData(keys.profile, next);
      void client.invalidateQueries({ queryKey: personalPlanKey });
    },
  });
  if (profile.isPending) return <Loading label="Loading your profile" />;
  if (profile.isError) return <ErrorNotice error={profile.error} />;
  const p = profile.data;
  const style: Style = p.plan_style ?? "weekly";
  const items = plan.data?.plan.items ?? [];
  const rehearsal = items.find((i) => i.kind === "rehearsal")?.title.split(":")[0];
  const story = items
    .find((i) => i.kind === "story" && i.key.startsWith("story:"))
    ?.title.replace(/^Get /, "")
    .replace(/ to Ready$/, "");
  // Counts from the groups: the weekly plan lists only this week's items.
  const open = (kind: string) => {
    const g = plan.data?.groups.find((x) => x.kind === kind);
    return g ? g.total - g.done : 0;
  };
  const issues = open("resume");
  const ideas = open("story");
  const email = auth.data?.user?.email ?? "";
  const summary = [p.full_name, email, p.target_level ? levelLabel[p.target_level] : null, p.years_experience !== null ? `${p.years_experience} years` : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="sx-page">
      <h1>Profile</h1>
      <section className="sx-card" aria-labelledby="plan-style-heading">
        <h2 id="plan-style-heading">Your plan style</h2>
        <p className="sx-small sx-muted">
          Strova keeps one plan for your stories, your resume and your interviews. Switch any time; your progress stays.
        </p>
        <PlanStyleChoices
          style={style}
          onChange={(next) => next !== style && settings.mutate({ plan_style: next })}
          examples={{ ideaCount: ideas, issueCount: issues, rehearsal, story }}
        />
        <p className="sx-small sx-muted">Both styles cover the same work: your stories, your resume and your mock interviews.</p>
      </section>
      <section className="sx-card" aria-labelledby="reminders-heading">
        <h2 id="reminders-heading">Reminders from Strova</h2>
        <div className="sx-between">
          <div>
            <strong>In the app</strong>
            <br />
            <span className="sx-small sx-muted">When a plan item is due, or your interview is close.</span>
          </div>
          <span className="sx-chip ok">On</span>
        </div>
        <div className="sx-between">
          <div>
            <strong>By email</strong>
            <br />
            <span className="sx-small sx-muted">
              {style === "weekly"
                ? 'Same reminders, from "Strova from Strong Hire".'
                : "Reminders are sent with the weekly plan only."}
            </span>
          </div>
          {p.plan_email_muted ? (
            <span className="sx-row">
              <span className="sx-chip">Muted</span>
              <button
                type="button"
                className="sx-btn ghost sm"
                disabled={settings.isPending}
                onClick={() => settings.mutate({ plan_email_muted: false })}
              >
                Unmute email
              </button>
            </span>
          ) : (
            <button
              type="button"
              className="sx-btn ghost sm"
              disabled={settings.isPending}
              onClick={() => settings.mutate({ plan_email_muted: true })}
            >
              Mute email
            </button>
          )}
        </div>
        {settings.isError && <ErrorNotice error={settings.error} />}
      </section>
      <section className="sx-card" aria-labelledby="account-heading">
        <h2 id="account-heading">Account</h2>
        <span className="sx-small">{summary}</span>
        <span className="sx-small sx-muted">
          Billing, data export and account deletion live on <Link to="/account">Account</Link>.
        </span>
      </section>
      <section className="sx-card" aria-labelledby="details-heading">
        <h2 id="details-heading">Your details</h2>
        <ProfileForm initial={p} submitLabel="Save profile" saving={saving} error={saveError} onSave={onSave} />
        <p role="status" className="sx-small sx-muted">
          {saved && "Saved. Your profile is up to date."}
        </p>
      </section>
    </div>
  );
}
