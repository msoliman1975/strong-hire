import { useId, useState, type FormEvent, type ReactNode } from "react";

import type { AlertMetric, AlertRule, AlertState } from "../api/alerts";
import { useAlertRules } from "../api/alerts";
import { ErrorNotice } from "./ui";

const STATE_LABEL: Record<AlertState, string> = { ok: "OK", pending: "Pending", firing: "Firing" };

export function StateBadge({ state }: { state: AlertState }) {
  return (
    <span className="badge badge--state" data-state={state}>
      {STATE_LABEL[state]}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: AlertRule["severity"] }) {
  return (
    <span className="badge badge--severity" data-severity={severity}>
      {severity}
    </span>
  );
}

/** The firing-rules count next to "Alerts" in the nav. Nothing while every rule is OK. */
export function FiringCount() {
  const rules = useAlertRules();
  const firing = rules.data?.filter((r) => r.enabled && r.state === "firing").length ?? 0;
  if (firing === 0) return null;
  return (
    <span className="badge badge--count" aria-label={`${firing} firing`}>
      {firing}
    </span>
  );
}

const COMPARATOR: Record<AlertRule["comparator"], string> = { gt: ">", gte: "≥", lt: "<", lte: "≤" };

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "never";
  if (seconds === 0) return "0 min";
  if (seconds % 86_400 === 0) return `${seconds / 86_400} d`;
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

export function labelsText(labels: AlertRule["labels"]): string {
  if (!labels) return "";
  return Object.entries(labels)
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("|") : v}`)
    .join(", ");
}

/** Parses `service=worker|voice, mount=root`. Returns null when the text is not valid. */
export function parseLabels(text: string): AlertRule["labels"] | null {
  const trimmed = text.trim();
  if (!trimmed) return {};
  const out: NonNullable<AlertRule["labels"]> = {};
  for (const part of trimmed.split(",")) {
    const [key, value, ...rest] = part.split("=").map((s) => s.trim());
    if (!key || !value || rest.length) return null;
    const values = value.split("|").map((s) => s.trim()).filter(Boolean);
    if (!values.length) return null;
    out[key] = values.length === 1 ? values[0] : values;
  }
  return out;
}

export function formatValue(value: number | null | undefined, unit = ""): string {
  if (value === null || value === undefined) return "-";
  const text = Math.abs(value) >= 100 || Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2);
  return unit ? `${text} ${unit}` : text;
}

/** `avg(host.disk_pct {mount=root}) over 5 min > 85 %`. */
export function conditionText(rule: AlertRule, metric?: AlertMetric): string {
  const labels = labelsText(rule.labels);
  const unit = metric?.unit ?? "";
  return (
    `${rule.aggregation}(${rule.metric}${labels ? ` {${labels}}` : ""}) over ${duration(rule.window_s)} ` +
    `${COMPARATOR[rule.comparator]} ${formatValue(rule.threshold, unit)}`
  );
}

/**
 * Confirm a write and collect its reason (AA-6, AA-7). Shown in place, so it works on any screen
 * width. `children` adds fields such as the mute duration.
 */
export function ReasonPrompt({
  title,
  detail,
  confirmLabel,
  pending,
  error,
  onConfirm,
  onCancel,
  children,
}: {
  title: string;
  detail: ReactNode;
  confirmLabel: string;
  pending: boolean;
  error: unknown;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
  children?: ReactNode;
}) {
  const [reason, setReason] = useState("");
  const id = useId();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (reason.trim().length >= 3) onConfirm(reason.trim());
  };
  return (
    <div className="panel prompt" role="dialog" aria-modal="false" aria-labelledby={`${id}-title`}>
      <form onSubmit={submit}>
        <h2 id={`${id}-title`}>{title}</h2>
        <p>{detail}</p>
        {children}
        <div className="field">
          <label htmlFor={`${id}-reason`}>Reason (saved in the audit log)</label>
          <input
            id={`${id}-reason`}
            value={reason}
            minLength={3}
            maxLength={500}
            required
            autoFocus
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
        {error ? <ErrorNotice error={error} /> : null}
        <div className="row">
          <button type="submit" className="btn btn--primary" disabled={pending || reason.trim().length < 3}>
            {confirmLabel}
          </button>
          <button type="button" className="btn" onClick={onCancel} disabled={pending}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
