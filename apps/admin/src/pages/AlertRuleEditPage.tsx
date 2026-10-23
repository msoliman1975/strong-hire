import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import {
  type AlertMetric,
  type AlertRule,
  type AlertRuleCreate,
  alertsApi,
  useAlertMetrics,
  useAlertRules,
  useAlertWrite,
} from "../api/alerts";
import { ReasonPrompt, StateBadge, labelsText, parseLabels } from "../components/alerts";
import { ErrorNotice, Loading, PageHead } from "../components/ui";

type Aggregation = AlertRule["aggregation"];
const AGGREGATIONS: Aggregation[] = ["last", "avg", "p95", "rate", "count"];
const COMPARATORS: { value: AlertRule["comparator"]; label: string }[] = [
  { value: "gt", label: "> greater than" },
  { value: "gte", label: "≥ at least" },
  { value: "lt", label: "< less than" },
  { value: "lte", label: "≤ at most" },
];

interface Draft {
  name: string;
  metric: string;
  labels: string;
  aggregation: Aggregation;
  windowMin: string;
  comparator: AlertRule["comparator"];
  threshold: string;
  minSamples: string;
  forMin: string;
  severity: AlertRule["severity"];
  renotifyMin: string;
  enabled: boolean;
}

const minutes = (s: number | null | undefined) => (s === null || s === undefined ? "" : String(s / 60));

function draftOf(rule: AlertRule | undefined): Draft {
  if (!rule) {
    return {
      name: "",
      metric: "host.disk_pct",
      labels: "",
      aggregation: "last",
      windowMin: "5",
      comparator: "gt",
      threshold: "",
      minSamples: "1",
      forMin: "0",
      severity: "warning",
      renotifyMin: "1440",
      enabled: true,
    };
  }
  return {
    name: rule.name,
    metric: rule.metric,
    labels: labelsText(rule.labels),
    aggregation: rule.aggregation,
    windowMin: minutes(rule.window_s),
    comparator: rule.comparator,
    threshold: String(rule.threshold),
    minSamples: String(rule.min_samples),
    forMin: minutes(rule.for_s),
    severity: rule.severity,
    renotifyMin: minutes(rule.renotify_s),
    enabled: rule.enabled,
  };
}

/** The body for the API, or an error message for the form. */
function toBody(d: Draft, metric: AlertMetric | undefined): { body?: Omit<AlertRuleCreate, "reason">; error?: string } {
  const labels = parseLabels(d.labels);
  if (labels === null) return { error: "Labels: write key=value, with | between values (service=worker|voice)." };
  const num = (s: string) => (s.trim() === "" ? NaN : Number(s));
  const threshold = num(d.threshold);
  const windowMin = num(d.windowMin);
  const forMin = d.forMin.trim() === "" ? 0 : num(d.forMin);
  const minSamples = num(d.minSamples);
  const renotify = d.renotifyMin.trim() === "" ? null : num(d.renotifyMin);
  if (!d.name.trim()) return { error: "The rule needs a name." };
  if (!Number.isFinite(threshold)) return { error: "The threshold must be a number." };
  if (!Number.isFinite(windowMin) || windowMin < 1) return { error: "The window is at least 1 minute." };
  if (!Number.isFinite(forMin) || forMin < 0) return { error: "'For' is 0 minutes or more." };
  if (!Number.isInteger(minSamples) || minSamples < 1) return { error: "Minimum samples is a whole number, 1 or more." };
  if (renotify !== null && (!Number.isFinite(renotify) || renotify < 5))
    return { error: "Re-send is at least 5 minutes, or empty for never." };
  return {
    body: {
      name: d.name.trim(),
      metric: d.metric,
      labels: Object.keys(labels ?? {}).length ? labels : null,
      aggregation: metric?.derived && metric.aggregation ? metric.aggregation : d.aggregation,
      window_s: Math.round(windowMin * 60),
      comparator: d.comparator,
      threshold,
      min_samples: minSamples,
      for_s: Math.round(forMin * 60),
      severity: d.severity,
      renotify_s: renotify === null ? null : Math.round(renotify * 60),
      enabled: d.enabled,
    },
  };
}

function RuleForm({ rule, metrics }: { rule?: AlertRule; metrics: AlertMetric[] }) {
  const navigate = useNavigate();
  const [draft, setDraft] = useState<Draft>(() => draftOf(rule));
  const [formError, setFormError] = useState("");
  const [confirm, setConfirm] = useState<"save" | "delete" | null>(null);
  const metric = metrics.find((m) => m.name === draft.metric);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const save = useAlertWrite(async (reason: string) => {
    const { body } = toBody(draft, metric);
    if (!body) throw new Error("Invalid form");
    if (rule) {
      // A default rule keeps its name; leave it out so the API does not see a rename.
      const { name, ...rest } = body;
      return alertsApi.update(rule.id, { ...(rule.is_default ? rest : { name, ...rest }), reason });
    }
    return alertsApi.create({ ...body, reason });
  });
  const remove = useAlertWrite(async (reason: string) => {
    if (rule) await alertsApi.remove(rule.id, reason);
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const { error } = toBody(draft, metric);
    setFormError(error ?? "");
    if (!error) setConfirm("save");
  };

  return (
    <>
      <form className="panel form-grid" onSubmit={submit} aria-label="Alert rule">
        <div className="field">
          <label htmlFor="rule-name">Name</label>
          <input
            id="rule-name"
            value={draft.name}
            maxLength={100}
            disabled={rule?.is_default}
            onChange={(e) => set("name", e.target.value)}
          />
          {rule?.is_default && <span className="muted">Default rules keep their name.</span>}
        </div>
        <div className="field">
          <label htmlFor="rule-metric">Metric</label>
          <select
            id="rule-metric"
            value={draft.metric}
            onChange={(e) => {
              const next = metrics.find((m) => m.name === e.target.value);
              setDraft((d) => ({
                ...d,
                metric: e.target.value,
                aggregation: next?.derived && next.aggregation ? next.aggregation : d.aggregation,
                labels: next?.labels.length ? d.labels : "",
              }));
            }}
          >
            {metrics.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
          </select>
          {metric && (
            <span className="muted">
              {metric.description}
              {metric.unit ? ` (${metric.unit})` : ""}
              {metric.up ? ". No sample in the window counts as down." : ""}
            </span>
          )}
        </div>
        <div className="field">
          <label htmlFor="rule-labels">Labels</label>
          <input
            id="rule-labels"
            value={draft.labels}
            disabled={!metric?.labels.length}
            placeholder={metric?.labels.length ? `${metric.labels[0]}=value (empty: every series)` : "No labels"}
            onChange={(e) => set("labels", e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="rule-aggregation">Aggregation</label>
          <select
            id="rule-aggregation"
            value={draft.aggregation}
            disabled={metric?.derived}
            onChange={(e) => set("aggregation", e.target.value as Aggregation)}
          >
            {AGGREGATIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="rule-window">Window (minutes)</label>
          <input id="rule-window" inputMode="decimal" value={draft.windowMin} onChange={(e) => set("windowMin", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rule-comparator">Fires when the value is</label>
          <select
            id="rule-comparator"
            value={draft.comparator}
            onChange={(e) => set("comparator", e.target.value as AlertRule["comparator"])}
          >
            {COMPARATORS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="rule-threshold">Threshold{metric?.unit ? ` (${metric.unit})` : ""}</label>
          <input id="rule-threshold" inputMode="decimal" value={draft.threshold} onChange={(e) => set("threshold", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rule-min">Minimum samples</label>
          <input id="rule-min" inputMode="numeric" value={draft.minSamples} onChange={(e) => set("minSamples", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rule-for">For (minutes before firing)</label>
          <input id="rule-for" inputMode="decimal" value={draft.forMin} onChange={(e) => set("forMin", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rule-severity">Severity</label>
          <select
            id="rule-severity"
            value={draft.severity}
            onChange={(e) => set("severity", e.target.value as AlertRule["severity"])}
          >
            <option value="critical">critical</option>
            <option value="warning">warning</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="rule-renotify">Re-send while firing (minutes, empty: never)</label>
          <input
            id="rule-renotify"
            inputMode="decimal"
            value={draft.renotifyMin}
            onChange={(e) => set("renotifyMin", e.target.value)}
          />
        </div>
        <label className="check">
          <input type="checkbox" checked={draft.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          Enabled
        </label>
        {formError && (
          <p className="notice notice--error" role="alert">
            {formError}
          </p>
        )}
        <div className="row">
          <button type="submit" className="btn btn--primary">
            {rule ? "Save changes" : "Add rule"}
          </button>
          {rule && !rule.is_default && (
            <button type="button" className="btn" onClick={() => setConfirm("delete")}>
              Delete rule
            </button>
          )}
          <Link className="btn btn--ghost" to="/alerts/rules">
            Back to rules
          </Link>
        </div>
      </form>
      {confirm === "save" && (
        <ReasonPrompt
          title={rule ? `Save ${rule.name}?` : `Add ${draft.name.trim()}?`}
          detail="The engine uses the new rule from its next check, within a minute."
          confirmLabel={rule ? "Save" : "Add rule"}
          pending={save.isPending}
          error={save.error}
          onConfirm={(reason) => save.mutate(reason, { onSuccess: () => navigate("/alerts/rules") })}
          onCancel={() => setConfirm(null)}
        />
      )}
      {confirm === "delete" && rule && (
        <ReasonPrompt
          title={`Delete ${rule.name}?`}
          detail="The rule and its history are deleted. This cannot be undone."
          confirmLabel="Delete"
          pending={remove.isPending}
          error={remove.error}
          onConfirm={(reason) => remove.mutate(reason, { onSuccess: () => navigate("/alerts/rules") })}
          onCancel={() => setConfirm(null)}
        />
      )}
    </>
  );
}

/** New rule (/alerts/rules/new) or edit one (/alerts/rules/:ruleId). */
export function AlertRuleEditPage() {
  const { ruleId } = useParams();
  const isNew = !ruleId || ruleId === "new";
  const rules = useAlertRules();
  const metrics = useAlertMetrics();
  const rule = isNew ? undefined : rules.data?.find((r) => r.id === ruleId);

  return (
    <>
      <PageHead title={isNew ? "New alert rule" : (rule?.name ?? "Alert rule")}>
        {rule && (
          <p>
            Now <StateBadge state={rule.state} />
          </p>
        )}
      </PageHead>
      {(metrics.isPending || (!isNew && rules.isPending)) && <Loading label="Loading the rule" />}
      {metrics.isError && <ErrorNotice error={metrics.error} />}
      {rules.isError && <ErrorNotice error={rules.error} />}
      {!isNew && rules.data && !rule && <p>This rule does not exist.</p>}
      {metrics.data && (isNew || rule) && <RuleForm key={rule?.id ?? "new"} rule={rule} metrics={metrics.data} />}
    </>
  );
}
