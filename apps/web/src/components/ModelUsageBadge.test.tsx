/** Dev-only spend indicator for the claude profile cost limits. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ModelUsage } from "../api/types";
import { ModelUsageBadge } from "./ModelUsageBadge";

const tracked = (today: number, month: number): ModelUsage => ({
  profile: "claude",
  tracked: true,
  today: { spend_usd: today, budget_usd: 5, resets_at: "2026-10-08T00:00:00Z" },
  month: { spend_usd: month, budget_usd: 30, resets_at: "2026-11-01T00:00:00Z" },
  rpm_limit: 60,
});

describe("ModelUsageBadge", () => {
  it("shows spend today and this month against the budgets", () => {
    render(<ModelUsageBadge usage={tracked(0.1234, 2.5)} />);
    const badge = screen.getByTestId("model-usage");
    expect(badge).toHaveTextContent("claude $0.12 / $5.00 today · $2.50 / $30 this month");
    expect(badge).toHaveAttribute("title", expect.stringContaining("60 requests per minute"));
    expect(badge).not.toHaveAttribute("data-level");
  });

  it("warns at 80% of a budget", () => {
    render(<ModelUsageBadge usage={tracked(4.1, 2)} />);
    expect(screen.getByTestId("model-usage")).toHaveAttribute("data-level", "high");
  });

  it("is hidden when spend is not tracked", () => {
    const { container } = render(
      <ModelUsageBadge usage={{ profile: "hosted", tracked: false, today: null, month: null, rpm_limit: null }} />,
    );
    expect(container).toBeEmptyDOMElement();
    const { container: empty } = render(<ModelUsageBadge usage={undefined} />);
    expect(empty).toBeEmptyDOMElement();
  });
});
