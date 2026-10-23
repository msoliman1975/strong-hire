import { useState } from "react";
import { Link, NavLink } from "react-router";

import {
  type AlertRule,
  type AlertTestResult,
  alertsApi,
  useAlertMetrics,
  useAlertRules,
  useAlertWrite,
} from "../api/alerts";
import { ReasonPrompt, SeverityBadge, StateBadge, conditionText, duration, formatValue } from "../components/alerts";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";

type Action = { kind: "enable" | "disable" | "mute" | "unmute" | "test"; rule: AlertRule };

const MUTE_HOURS = [1, 4, 24, 72];

export function AlertsTabs() {
  return (
    <nav className="tabs" aria-label="Alerts">
      <NavLink to="/alerts/rules">Rules</NavLink>
      <NavLink to="/alerts/history">History</NavLink>
    </nav>
  );
}

function isMuted(rule: AlertRule): boolean {
  return !!rule.muted_until && new Date(rule.muted_until).getTime() > Date.now();
}

function ActionPrompt({ action, onDone }: { action: Action; onDone: (note: string) => void }) {
  const { kind, rule } = action;
  const [hours, setHours] = useState(4);
  const write = useAlertWrite(async (reason: string): Promise<string> => {
    if (kind === "enable" || kind === "disable") {
      await alertsApi.update(rule.id, { enabled: kind === "enable", reason });
      return `${rule.name} is ${kind === "enable" ? "enabled" : "disabled"}.`;
    }
    if (kind === "mute") {
      const until = new Date(Date.now() + hours * 3_600_000).toISOString();
      await alertsApi.mute(rule.id, until, reason);
      return `${rule.name} is muted for ${hours} h.`;
    }
    if (kind === "unmute") {
      await alertsApi.mute(rule.id, null, reason);
      return `${rule.name} is unmuted.`;
    }
    const result: AlertTestResult = await alertsApi.test(rule.id, reason);
    return result.sent
      ? `Test alert for ${rule.name} sent to the alert address.`
      : `Test alert for ${rule.name} not sent: ${result.error ?? "unknown error"}. The engine retries it.`;
  });
  const title = {
    enable: `Enable ${rule.name}?`,
    disable: `Disable ${rule.name}?`,
    mute: `Mute ${rule.name}?`,
    unmute: `Unmute ${rule.name}?`,
    test: `Send a test alert for ${rule.name}?`,
  }[kind];
  const detail = {
    enable: "The engine checks it again from the next minute.",
    disable: "The engine stops checking it, and its state goes back to OK. No email is sent.",
    mute: "Its state still changes, but no email goes out until the mute ends.",
    unmute: "Emails go out again. If it is firing now, one goes out within a minute.",
    test: "One email goes to ALERT_EMAIL now. Nothing else changes.",
  }[kind];
  return (
    <ReasonPrompt
      title={title}
      detail={detail}
      confirmLabel={{ enable: "Enable", disable: "Disable", mute: "Mute", unmute: "Unmute", test: "Send test" }[kind]}
      pending={write.isPending}
      error={write.error}
      onConfirm={(reason) => write.mutate(reason, { onSuccess: onDone })}
      onCancel={() => onDone("")}
    >
      {kind === "mute" && (
        <div className="field">
          <label htmlFor="mute-hours">Mute for</label>
          <select id="mute-hours" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {MUTE_HOURS.map((h) => (
              <option key={h} value={h}>
                {h} h
              </option>
            ))}
          </select>
        </div>
      )}
    </ReasonPrompt>
  );
}

/** AL-1, AL-4, AL-6: every rule with its state, and the actions on it. */
export function AlertRulesPage() {
  const rules = useAlertRules();
  const metrics = useAlertMetrics();
  const [action, setAction] = useState<Action | null>(null);
  const [note, setNote] = useState("");
  const byName = new Map((metrics.data ?? []).map((m) => [m.name, m]));

  return (
    <>
      <PageHead title="Alert rules">
        <p>
          The engine checks each enabled rule every minute and emails the alert address when one starts or stops
          firing.
        </p>
      </PageHead>
      <AlertsTabs />
      <div className="row section-gap">
        <Link className="btn btn--primary" to="/alerts/rules/new">
          New rule
        </Link>
      </div>
      {note && (
        <p className="notice" role="status">
          {note}
        </p>
      )}
      {action && (
        <ActionPrompt
          key={`${action.kind}-${action.rule.id}`}
          action={action}
          onDone={(message) => {
            setAction(null);
            setNote(message);
          }}
        />
      )}
      {rules.isPending && <Loading label="Loading the alert rules" />}
      {rules.isError && <ErrorNotice error={rules.error} />}
      {rules.data && rules.data.length === 0 && <p>No rules yet. The worker adds the default rules when it starts.</p>}
      {rules.data && rules.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">State</th>
                <th scope="col">Rule</th>
                <th scope="col">Condition</th>
                <th scope="col" className="num">
                  Value
                </th>
                <th scope="col">Since</th>
                <th scope="col">Enabled</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rules.data.map((r) => {
                const muted = isMuted(r);
                return (
                  <tr key={r.id} data-state={r.state}>
                    <td>
                      <StateBadge state={r.state} />
                    </td>
                    <td>
                      <Link to={`/alerts/rules/${r.id}`}>{r.name}</Link>
                      <div className="row row--tight">
                        <SeverityBadge severity={r.severity} />
                        {muted && <span className="tag">Muted until {utc(r.muted_until)}</span>}
                      </div>
                    </td>
                    <td className="mono-small">
                      {conditionText(r, byName.get(r.metric))}
                      <div className="muted">
                        for {duration(r.for_s)}, min {r.min_samples} samples, re-send {duration(r.renotify_s)}
                      </div>
                    </td>
                    <td className="num">{formatValue(r.last_value, byName.get(r.metric)?.unit)}</td>
                    <td>{r.state === "ok" ? "-" : utc(r.state_since)}</td>
                    <td>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={r.enabled}
                          onChange={() => setAction({ kind: r.enabled ? "disable" : "enable", rule: r })}
                        />
                        <span className="visually-hidden">Enabled: {r.name}</span>
                      </label>
                    </td>
                    <td>
                      <div className="row row--tight">
                        <Link className="btn btn--small" to={`/alerts/rules/${r.id}`}>
                          Edit
                        </Link>
                        <button
                          type="button"
                          className="btn btn--small"
                          onClick={() => setAction({ kind: muted ? "unmute" : "mute", rule: r })}
                        >
                          {muted ? "Unmute" : "Mute"}
                        </button>
                        <button type="button" className="btn btn--small" onClick={() => setAction({ kind: "test", rule: r })}>
                          Test
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
