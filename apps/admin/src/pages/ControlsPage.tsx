import { useState, type ReactNode } from "react";

import {
  activeControls,
  bannerActive,
  JOB_KINDS,
  useOpsModels,
  useOpsSettings,
  useSetSetting,
  type BannerSeverity,
  type CustomAccess,
  type JobKind,
  type OpsSettings,
  type SettingKey,
} from "../api/controls";
import { ReasonDialog } from "../components/ReasonDialog";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";

interface Change {
  key: SettingKey;
  value: unknown;
  title: string;
  summary: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  requireWord?: string;
}

const SEVERITIES: BannerSeverity[] = ["info", "warning", "critical"];

function inFuture(ms: number): boolean {
  return Number.isFinite(ms) && ms > Date.now();
}

/** A datetime-local value (the admin's local time) two hours from now. */
function inTwoHours(): string {
  const d = new Date(Date.now() + 2 * 3600_000);
  d.setSeconds(0, 0);
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function LastChanged({ settings, keyName }: { settings: OpsSettings; keyName: SettingKey }) {
  const meta = settings.meta.find((m) => m.key === keyName);
  if (!meta?.updated_by) return <p className="muted small">Never changed: the default is in force.</p>;
  return (
    <p className="muted small">
      Last changed by {meta.updated_by}, {utc(meta.updated_at)}
    </p>
  );
}

function State({ on, onLabel, offLabel }: { on: boolean; onLabel: string; offLabel: string }) {
  return (
    <span className={on ? "state state--off" : "state state--on"}>{on ? onLabel : offLabel}</span>
  );
}

export function BannerPreview({ text, severity }: { text: string; severity: BannerSeverity }) {
  return (
    <div className="site-banner-preview" data-severity={severity} role="note" aria-label="Banner preview">
      {text || "Banner text"}
    </div>
  );
}

function SignupsControl({ settings, ask }: { settings: OpsSettings; ask: (c: Change) => void }) {
  const paused = settings.values.signups_paused;
  return (
    <section className="panel control" aria-labelledby="ctl-signups">
      <h2 id="ctl-signups">Sign-ups (OC-1)</h2>
      <p>
        <State on={paused} onLabel="Paused" offLabel="Open" /> New accounts are refused with a waitlist message
        while paused. Existing users can still sign in.
      </p>
      <LastChanged settings={settings} keyName="signups_paused" />
      <button
        type="button"
        className={paused ? "btn btn--primary" : "btn btn--danger"}
        onClick={() =>
          ask({
            key: "signups_paused",
            value: !paused,
            title: paused ? "Open sign-ups" : "Pause sign-ups",
            summary: paused ? (
              <p>New people can create accounts again.</p>
            ) : (
              <p>
                Every new account (password, email link, Google) will be refused with a waitlist message.
              </p>
            ),
            confirmLabel: paused ? "Open sign-ups" : "Pause sign-ups",
            danger: !paused,
          })
        }
      >
        {paused ? "Open sign-ups" : "Pause sign-ups"}
      </button>
    </section>
  );
}

function SessionsControl({ settings, ask }: { settings: OpsSettings; ask: (c: Change) => void }) {
  const channels: { key: SettingKey; label: string; paused: boolean }[] = [
    { key: "sessions_paused_voice", label: "Voice", paused: settings.values.sessions_paused_voice },
    { key: "sessions_paused_text", label: "Text", paused: settings.values.sessions_paused_text },
  ];
  return (
    <section className="panel control" aria-labelledby="ctl-sessions">
      <h2 id="ctl-sessions">New sessions (OC-2)</h2>
      <p>Starting a session answers "temporarily unavailable" while paused. Sessions in progress go on.</p>
      <ul className="control__list">
        {channels.map((c) => (
          <li key={c.key}>
            <span className="control__name">{c.label}</span>
            <State on={c.paused} onLabel="Paused" offLabel="Open" />
            <button
              type="button"
              className={c.paused ? "btn btn--small btn--primary" : "btn btn--small btn--danger"}
              onClick={() =>
                ask({
                  key: c.key,
                  value: !c.paused,
                  title: c.paused ? `Resume ${c.label.toLowerCase()} sessions` : `Pause ${c.label.toLowerCase()} sessions`,
                  summary: c.paused ? (
                    <p>New {c.label.toLowerCase()} sessions can start again.</p>
                  ) : (
                    <p>
                      Every new <strong>{c.label.toLowerCase()}</strong> session will be refused. Sessions in progress
                      continue.
                    </p>
                  ),
                  confirmLabel: c.paused ? "Resume" : "Pause sessions",
                  danger: !c.paused,
                  requireWord: c.paused ? undefined : "PAUSE",
                })
              }
            >
              {c.paused ? `Resume ${c.label.toLowerCase()}` : `Pause ${c.label.toLowerCase()}`}
            </button>
            <LastChanged settings={settings} keyName={c.key} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function SpendCapControl({ settings, ask }: { settings: OpsSettings; ask: (c: Change) => void }) {
  const cap = settings.values.daily_spend_cap_usd;
  const [draft, setDraft] = useState(String(cap));
  const value = Number(draft);
  const valid = draft.trim() !== "" && Number.isFinite(value) && value >= 0;
  const spent = settings.spend_today_usd;
  const pct = cap > 0 ? Math.min(100, (spent / cap) * 100) : 100;
  return (
    <section className="panel control" aria-labelledby="ctl-spend">
      <h2 id="ctl-spend">Daily spend cap (OC-3)</h2>
      <p>
        Today (since 00:00 UTC): <strong>${spent.toFixed(2)}</strong> of ${cap.toFixed(2)}. At the cap, new
        sessions are refused; sessions in progress finish.
      </p>
      <div className="meter" role="img" aria-label={`${pct.toFixed(0)}% of the daily cap`}>
        <span style={{ width: `${pct}%` }} data-level={pct >= 100 ? "critical" : pct >= 80 ? "warning" : "ok"} />
      </div>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          if (!valid || value === cap) return;
          ask({
            key: "daily_spend_cap_usd",
            value,
            title: "Change the daily spend cap",
            summary: (
              <p>
                Daily cap: ${cap.toFixed(2)} → <strong>${value.toFixed(2)}</strong> (default $
                {settings.defaults.daily_spend_cap_usd.toFixed(2)}).
              </p>
            ),
            confirmLabel: "Save cap",
            danger: value < spent,
          });
        }}
      >
        <div className="field">
          <label htmlFor="spend-cap">Cap in USD</label>
          <input
            id="spend-cap"
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </div>
        <button type="submit" className="btn btn--primary" disabled={!valid || value === cap}>
          Save cap
        </button>
      </form>
      <LastChanged settings={settings} keyName="daily_spend_cap_usd" />
    </section>
  );
}

function BannerControl({ settings, ask }: { settings: OpsSettings; ask: (c: Change) => void }) {
  const current = settings.values.site_banner;
  const [text, setText] = useState(current?.text ?? "");
  const [severity, setSeverity] = useState<BannerSeverity>(current?.severity ?? "info");
  const [until, setUntil] = useState(inTwoHours);
  const untilMs = Date.parse(until);
  const valid = text.trim().length > 0 && text.length <= 500 && inFuture(untilMs);
  const shown = bannerActive(current);
  return (
    <section className="panel control" aria-labelledby="ctl-banner">
      <h2 id="ctl-banner">Site banner (OC-4)</h2>
      {current ? (
        <p>
          <State on={shown} onLabel="Shown" offLabel="Ended" /> Until {utc(current.until)}: "{current.text}"
        </p>
      ) : (
        <p>No banner. The candidate app shows it on every page until its end time.</p>
      )}
      <LastChanged settings={settings} keyName="site_banner" />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!valid) return;
          const value = { text: text.trim(), severity, until: new Date(untilMs).toISOString() };
          ask({
            key: "site_banner",
            value,
            title: "Show the site banner",
            summary: (
              <>
                <BannerPreview text={value.text} severity={severity} />
                <p>Shown to every candidate until {utc(value.until)}.</p>
              </>
            ),
            confirmLabel: "Show banner",
          });
        }}
      >
        <div className="field">
          <label htmlFor="banner-text">Text</label>
          <input id="banner-text" maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <div className="row">
          <div className="field">
            <label htmlFor="banner-severity">Severity</label>
            <select
              id="banner-severity"
              value={severity}
              onChange={(e) => setSeverity(e.target.value as BannerSeverity)}
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="banner-until">Ends (your local time)</label>
            <input id="banner-until" type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
          </div>
        </div>
        <p className="label">Preview</p>
        <BannerPreview text={text.trim()} severity={severity} />
        <div className="row">
          <button type="submit" className="btn btn--primary" disabled={!valid}>
            Show banner
          </button>
          {current && (
            <button
              type="button"
              className="btn"
              onClick={() =>
                ask({
                  key: "site_banner",
                  value: null,
                  title: "Remove the site banner",
                  summary: <p>The banner "{current.text}" is removed from the candidate app.</p>,
                  confirmLabel: "Remove banner",
                })
              }
            >
              Remove banner
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

function JobsControl({ settings, ask }: { settings: OpsSettings; ask: (c: Change) => void }) {
  const saved = settings.values.jobs_paused;
  const [draft, setDraft] = useState<JobKind[]>(saved);
  const changed = draft.length !== saved.length || draft.some((k) => !saved.includes(k));
  const names = (kinds: JobKind[]) =>
    kinds.length ? JOB_KINDS.filter((j) => kinds.includes(j.kind)).map((j) => j.label).join(", ") : "none";
  return (
    <section className="panel control" aria-labelledby="ctl-jobs">
      <h2 id="ctl-jobs">Background jobs (OC-5)</h2>
      <p>Paused jobs wait in the queue and retry every minute, for incidents with a model provider.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!changed) return;
          ask({
            key: "jobs_paused",
            value: draft,
            title: "Change paused jobs",
            summary: (
              <p>
                Paused: {names(saved)} → <strong>{names(draft)}</strong>
              </p>
            ),
            confirmLabel: "Save",
            danger: draft.length > saved.length,
          });
        }}
      >
        <fieldset>
          <legend className="label">Pause</legend>
          {JOB_KINDS.map(({ kind, label }) => (
            <label key={kind} className="check">
              <input
                type="checkbox"
                checked={draft.includes(kind)}
                onChange={(e) =>
                  setDraft((d) => (e.target.checked ? [...d, kind] : d.filter((k) => k !== kind)))
                }
              />
              {label}
              {saved.includes(kind) && <span className="tag"> paused</span>}
            </label>
          ))}
        </fieldset>
        <button type="submit" className="btn btn--primary" disabled={!changed}>
          Save jobs
        </button>
      </form>
      <LastChanged settings={settings} keyName="jobs_paused" />
    </section>
  );
}

const CUSTOM_ACCESS: { value: CustomAccess; label: string; hint: string }[] = [
  { value: "everyone", label: "Everyone", hint: "Every user. Free accounts may run a 30-minute Custom interview." },
  { value: "paid_only", label: "Paid plans only", hint: "Free accounts see Custom locked with an upgrade prompt." },
];

/** CU-11: who may build and run Custom interviews. */
function CustomAccessControl({ settings, ask }: { settings: OpsSettings; ask: (c: Change) => void }) {
  const current = settings.values.custom_interview_access;
  const label = (v: CustomAccess) => CUSTOM_ACCESS.find((a) => a.value === v)?.label ?? v;
  return (
    <section className="panel control" aria-labelledby="ctl-custom">
      <h2 id="ctl-custom">Custom interviews (CU-11)</h2>
      <p>
        Open to: <strong data-testid="custom-access">{label(current)}</strong>. Under paid plans only, a free account
        cannot start a Custom interview or check its own questions; saved questions stay.
      </p>
      <ul className="control__list">
        {CUSTOM_ACCESS.map((a) => (
          <li key={a.value}>
            <span className="control__name">{a.label}</span>
            <span className="muted small">{a.hint}</span>
            {a.value === current ? (
              <span className="state state--on">Current</span>
            ) : (
              <button
                type="button"
                className={a.value === "paid_only" ? "btn btn--small btn--danger" : "btn btn--small btn--primary"}
                onClick={() =>
                  ask({
                    key: "custom_interview_access",
                    value: a.value,
                    title: a.value === "paid_only" ? "Limit Custom to paid plans" : "Open Custom to everyone",
                    summary: (
                      <p>
                        Custom interviews: {label(current)} → <strong>{a.label}</strong>. {a.hint}
                      </p>
                    ),
                    confirmLabel: a.value === "paid_only" ? "Limit to paid plans" : "Open to everyone",
                    danger: a.value === "paid_only",
                  })
                }
              >
                {a.value === "paid_only" ? "Limit to paid plans" : "Open to everyone"}
              </button>
            )}
          </li>
        ))}
      </ul>
      <LastChanged settings={settings} keyName="custom_interview_access" />
    </section>
  );
}

function ModelProfilePanel() {
  const models = useOpsModels();
  return (
    <section className="panel control control--wide" aria-labelledby="ctl-models">
      <h2 id="ctl-models">Model profile (OC-6)</h2>
      <p className="muted">
        Read-only. Changing the profile is an .env edit and a restart (D-11).
      </p>
      {models.isPending && <Loading label="Loading the model profile" />}
      {models.isError && <ErrorNotice error={models.error} />}
      {models.data && (
        <>
          <p>
            API profile: <strong>{models.data.api_profile}</strong>
          </p>
          {models.data.mismatch && (
            <div className="notice notice--error" role="alert">
              <p>Services run different model profiles. Check the .env of each service and restart.</p>
            </div>
          )}
          <h3>Services</h3>
          {!models.data.heartbeats_available && (
            <p className="muted">The service heartbeats could not be read from Redis.</p>
          )}
          {models.data.heartbeats_available && models.data.services.length === 0 && (
            <p className="muted">No service heartbeats yet.</p>
          )}
          {models.data.services.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Service</th>
                    <th scope="col">Instance</th>
                    <th scope="col">Profile</th>
                    <th scope="col">Version</th>
                    <th scope="col">Last heartbeat</th>
                  </tr>
                </thead>
                <tbody>
                  {models.data.services.map((s) => (
                    <tr key={`${s.service}:${s.instance}`}>
                      <td>{s.service}</td>
                      <td>{s.instance}</td>
                      <td>
                        {s.model_profile ?? "-"}
                        {s.model_profile && s.model_profile !== models.data.api_profile && (
                          <span className="tag"> differs</span>
                        )}
                      </td>
                      <td>{s.version ?? "-"}</td>
                      <td>{utc(s.at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h3>Roles</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Role</th>
                  <th scope="col">Alias</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Tier</th>
                </tr>
              </thead>
              <tbody>
                {models.data.roles.map((r) => (
                  <tr key={r.role}>
                    <td>
                      {r.role}
                      {r.test_only && <span className="tag"> test only</span>}
                    </td>
                    <td>
                      <code>{r.alias}</code>
                    </td>
                    <td>{r.kind}</td>
                    <td>{r.tier ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

/** Operations → Controls: runtime settings without a redeploy (OC-1 to OC-6, AA-7, CU-11). */
export function ControlsPage() {
  const settings = useOpsSettings();
  const setSetting = useSetSetting();
  const [change, setChange] = useState<Change | null>(null);

  const ask = (c: Change) => {
    setSetting.reset();
    setChange(c);
  };
  const close = () => setChange(null);

  return (
    <>
      <PageHead title="Controls">
        <p>Runtime controls. Each change takes effect within about 10 seconds and is audited.</p>
      </PageHead>
      {settings.isPending && <Loading label="Loading the controls" />}
      {settings.isError && <ErrorNotice error={settings.error} />}
      {settings.data && (
        <>
          {activeControls(settings.data).length === 0 && (
            <p className="muted">Every control is at its default.</p>
          )}
          <div className="controls-grid">
            <SignupsControl settings={settings.data} ask={ask} />
            <SessionsControl settings={settings.data} ask={ask} />
            <SpendCapControl key={`cap-${settings.data.values.daily_spend_cap_usd}`} settings={settings.data} ask={ask} />
            <JobsControl key={`jobs-${settings.data.values.jobs_paused.join(",")}`} settings={settings.data} ask={ask} />
            <BannerControl settings={settings.data} ask={ask} />
            <CustomAccessControl settings={settings.data} ask={ask} />
          </div>
        </>
      )}
      <ModelProfilePanel />
      {change && (
        <ReasonDialog
          title={change.title}
          confirmLabel={change.confirmLabel}
          danger={change.danger}
          requireWord={change.requireWord}
          pending={setSetting.isPending}
          error={setSetting.isError ? setSetting.error : undefined}
          onCancel={close}
          onConfirm={(reason) =>
            setSetting.mutate({ key: change.key, value: change.value, reason }, { onSuccess: close })
          }
        >
          {change.summary}
        </ReasonDialog>
      )}
    </>
  );
}
