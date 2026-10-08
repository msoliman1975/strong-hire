import type { ModelUsage } from "../api/types";

type Budget = NonNullable<ModelUsage["today"]>;

const money = (value: number) => `$${value < 10 ? value.toFixed(2) : value.toFixed(0)}`;

function part(label: string, budget: Budget | null | undefined): { text: string; high: boolean } | null {
  if (!budget) return null;
  const cap = budget.budget_usd ?? 0;
  const high = cap > 0 && budget.spend_usd / cap >= 0.8;
  const of = cap > 0 ? ` / ${money(cap)}` : "";
  return { text: `${money(budget.spend_usd)}${of} ${label}`, high };
}

/**
 * Testing and validation: Claude spend against the daily and monthly budgets of the app's LiteLLM
 * key. Hidden when the profile does not track spend or the API does not answer (useModelUsage).
 */
export function ModelUsageBadge({ usage }: { usage: ModelUsage | undefined }) {
  if (!usage?.tracked) return null;
  const parts = [part("today", usage.today), part("this month", usage.month)].filter(
    (p): p is { text: string; high: boolean } => p !== null,
  );
  const high = parts.some((p) => p.high);
  const title =
    `Model spend for the ${usage.profile} profile (dev only).` +
    (usage.rpm_limit ? ` Limit: ${usage.rpm_limit} requests per minute.` : "");
  return (
    <span className="model-usage" data-level={high ? "high" : undefined} title={title} data-testid="model-usage">
      <span className="model-usage__label">{usage.profile}</span> {parts.map((p) => p.text).join(" · ")}
    </span>
  );
}
