/** BL-1: the usage meter shows minutes used of the cap, exactly as the API reports them.
 * BL-2: on the free plan it shows the free interviews left, as a number from the API. */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { Usage } from "../api/types";
import { FREE_USAGE } from "../mocks/db";
import { UsageMeter } from "./UsageMeter";

const paid = (minutes_used: number): Usage => ({
  ...FREE_USAGE,
  plan: "paid",
  status: "active",
  minutes_used,
  minutes_cap: 300,
  minutes_left: Math.max(0, 300 - minutes_used),
  free_interviews_left: 0,
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
        <UsageMeter usage={FREE_USAGE} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link")).toHaveAttribute("href", "/upgrade");
    expect(screen.getByText("Free plan: 1 free interview left")).toBeInTheDocument();
  });

  it("uses the number of free interviews from the API", () => {
    render(
      <MemoryRouter>
        <UsageMeter usage={{ ...FREE_USAGE, free_interviews_total: 3, free_interviews_left: 2 }} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Free plan: 2 free interviews left")).toBeInTheDocument();
  });

  it("says when the free interview is used", () => {
    render(
      <MemoryRouter>
        <UsageMeter usage={{ ...FREE_USAGE, free_interviews_left: 0, can_start_session: false }} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Free plan: free interview used")).toBeInTheDocument();
  });
});
