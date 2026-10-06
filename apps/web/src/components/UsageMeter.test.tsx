/** BL-1: the usage meter shows minutes used of the cap, exactly as the API reports them. */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { Usage } from "../api/planned";
import { UsageMeter } from "./UsageMeter";

const paid = (minutes_used: number): Usage => ({
  plan: "paid",
  minutes_used,
  minutes_cap: 300,
  period_end: null,
  free_interview_available: false,
});

describe("UsageMeter", () => {
  it("shows minutes used of the cap as an accessible meter", () => {
    render(<UsageMeter usage={paid(120)} />);
    const meter = screen.getByRole("meter", { name: "120 of 300 minutes used" });
    expect(meter).toHaveAttribute("aria-valuenow", "120");
    expect(meter).toHaveAttribute("aria-valuemax", "300");
  });

  it("does not overflow when usage passes the cap", () => {
    render(<UsageMeter usage={paid(320)} />);
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "300");
  });

  it("shows the free interview on the free plan, with a link to upgrade", () => {
    render(
      <MemoryRouter>
        <UsageMeter
          usage={{ plan: "free", minutes_used: 0, minutes_cap: 0, period_end: null, free_interview_available: true }}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link")).toHaveAttribute("href", "/upgrade");
    expect(screen.getByText("Free plan: 1 free interview left")).toBeInTheDocument();
  });
});
