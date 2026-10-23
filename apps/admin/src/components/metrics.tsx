/**
 * KPI tiles for AdminMetric values (AO): the value, the change against the previous period, the
 * spec target, and "Not measured" with the reason when the app cannot measure it (AO-8). A tile
 * with a link opens the list behind the number (AO-7).
 */
import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router";

import type { AdminMetric } from "../api/ops";

export function formatValue(value: number | null | undefined, unit: AdminMetric["unit"]): string {
  if (value === null || value === undefined) return "-";
  switch (unit) {
    case "usd":
      return Math.abs(value) >= 100 ? `$${value.toFixed(0)}` : `$${value.toFixed(2)}`;
    case "pct":
      return `${(value * 100).toFixed(1)}%`;
    case "ms":
      return `${Math.round(value)} ms`;
    case "minutes":
      return `${Math.round(value)} min`;
    case "ratio":
    case "rating":
      return value.toFixed(2);
    case "bytes": {
      const units = ["B", "KB", "MB", "GB", "TB"];
      let v = value;
      let i = 0;
      while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i += 1;
      }
      return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
    }
    default:
      return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
}

/** "+12% vs previous" (or points for percentages). Null when there is nothing to compare. */
export function delta(metric: AdminMetric): string | null {
  const { value, previous } = metric;
  if (value === null || value === undefined || previous === null || previous === undefined) return null;
  if (metric.unit === "pct") {
    const pts = (value - previous) * 100;
    return `${pts >= 0 ? "+" : ""}${pts.toFixed(1)} pts`;
  }
  if (previous === 0) return value === 0 ? "no change" : "new";
  const pct = ((value - previous) / Math.abs(previous)) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(0)}%`;
}

export function Kpi({ label, metric }: { label: string; metric: AdminMetric }) {
  const unit = metric.unit ?? "count";
  if (metric.measured === false) {
    return (
      <div className="kpi kpi--unmeasured">
        <p className="kpi__label">{label}</p>
        <p className="kpi__value">Not measured</p>
        <p className="kpi__note">{metric.reason}</p>
      </div>
    );
  }
  const change = delta(metric);
  const value = formatValue(metric.value, unit);
  return (
    <div className="kpi">
      <p className="kpi__label">{label}</p>
      <p className="kpi__value">{metric.link ? <Link to={metric.link}>{value}</Link> : value}</p>
      <p className="kpi__delta">
        {change ? `${change} vs previous (${formatValue(metric.previous, unit)})` : "No previous value"}
      </p>
      {metric.target !== null && metric.target !== undefined && (
        <p className="kpi__note">Target {formatValue(metric.target, unit)}</p>
      )}
      {metric.note && <p className="kpi__note">{metric.note}</p>}
    </div>
  );
}

/**
 * AA-6, AA-7: a write needs a reason. The confirm button repeats the action and the target.
 */
export function ReasonButton({
  label,
  confirm,
  onSubmit,
  pending,
  error,
}: {
  label: string;
  confirm: string;
  onSubmit: (reason: string) => Promise<unknown>;
  pending: boolean;
  error?: unknown;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const id = useId();
  if (!open) {
    return (
      <button type="button" className="btn btn--small" onClick={() => setOpen(true)}>
        {label}
      </button>
    );
  }
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await onSubmit(reason.trim());
      setOpen(false);
      setReason("");
    } catch {
      // The error is shown below; the form stays open.
    }
  };
  return (
    <form className="reason" onSubmit={submit} aria-label={label}>
      <div className="field">
        <label htmlFor={id}>Reason (saved in the audit log)</label>
        <input id={id} value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} maxLength={500} required />
      </div>
      <div className="row">
        <button type="submit" className="btn btn--primary btn--small" disabled={pending || reason.trim().length < 3}>
          {confirm}
        </button>
        <button type="button" className="btn btn--ghost btn--small" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error instanceof Error && (
        <p className="notice notice--error" role="alert">
          {error.message}
        </p>
      )}
    </form>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const icon: Record<string, string> = { up: "●", degraded: "▲", down: "■", unknown: "?" };
  return (
    <span className={`status status--${status}`}>
      <span aria-hidden="true">{icon[status] ?? "?"}</span> {status}
    </span>
  );
}
