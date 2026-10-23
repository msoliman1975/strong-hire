import { useState } from "react";

import { type AlertEventFilters, type AlertEventKind, useAlertEvents, useAlertMetrics, useAlertRules } from "../api/alerts";
import { SeverityBadge, formatValue } from "../components/alerts";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";
import { AlertsTabs } from "./AlertRulesPage";

const RANGES = [
  { value: "1", label: "Last 24 hours" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "", label: "All" },
];

function sinceFor(days: string): string | undefined {
  return days ? new Date(Date.now() - Number(days) * 86_400_000).toISOString() : undefined;
}

const KIND_LABEL: Record<AlertEventKind, string> = { fired: "Fired", resolved: "Resolved", test: "Test" };

/** AL-4: what fired and resolved, newest first, and whether the email went out. */
export function AlertHistoryPage() {
  const [ruleId, setRuleId] = useState("");
  const [kind, setKind] = useState<AlertEventKind | "">("");
  const [days, setDays] = useState("7");
  // The range starts when it is picked, so the query key stays the same between renders.
  const [since, setSince] = useState(() => sinceFor("7"));
  const filters: AlertEventFilters = {
    ...(ruleId ? { rule_id: ruleId } : {}),
    ...(kind ? { kind } : {}),
    ...(since ? { since } : {}),
  };
  const events = useAlertEvents(filters);
  const rules = useAlertRules();
  const metrics = useAlertMetrics();
  const units = new Map((metrics.data ?? []).map((m) => [m.name, m.unit]));
  const metricOf = new Map((rules.data ?? []).map((r) => [r.id, r.metric]));

  return (
    <>
      <PageHead title="Alert history">
        <p>Every time a rule fired or resolved, and every test alert.</p>
      </PageHead>
      <AlertsTabs />
      <div className="filters section-gap">
        <div className="field">
          <label htmlFor="history-rule">Rule</label>
          <select id="history-rule" value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
            <option value="">All rules</option>
            {(rules.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="history-kind">Kind</label>
          <select id="history-kind" value={kind} onChange={(e) => setKind(e.target.value as AlertEventKind | "")}>
            <option value="">All kinds</option>
            <option value="fired">Fired</option>
            <option value="resolved">Resolved</option>
            <option value="test">Test</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="history-range">Range</label>
          <select id="history-range" value={days} onChange={(e) => {
              setDays(e.target.value);
              setSince(sinceFor(e.target.value));
            }}>
            {RANGES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {events.isPending && <Loading label="Loading the alert history" />}
      {events.isError && <ErrorNotice error={events.error} />}
      {events.data && events.data.length === 0 && <p>No alerts in this range.</p>}
      {events.data && events.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Rule</th>
                <th scope="col">Severity</th>
                <th scope="col">What</th>
                <th scope="col" className="num">
                  Value
                </th>
                <th scope="col">Email</th>
              </tr>
            </thead>
            <tbody>
              {events.data.map((e) => (
                <tr key={e.id}>
                  <td>{utc(e.at)}</td>
                  <td>{e.rule_name}</td>
                  <td>
                    <SeverityBadge severity={e.severity} />
                  </td>
                  <td>{KIND_LABEL[e.kind]}</td>
                  <td className="num">{formatValue(e.value, units.get(metricOf.get(e.rule_id) ?? ""))}</td>
                  <td>
                    {e.notified
                      ? "Sent"
                      : e.notify_error === "muted"
                        ? "Not sent (muted)"
                        : `Not sent: ${e.notify_error ?? "waiting"}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
