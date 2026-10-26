/**
 * Overview (AD-2, AO) and Operations pages (OB-10..OB-14) against the mocks: default route, nav
 * group, KPI tiles with deltas and "not measured", links to the filtered lists, error resolve and
 * job retry with a reason.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { configure, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { mockSignIn } from "../mocks/handlers";
import { mockStore } from "../mocks/node";

// These pages render many tiles; give slow CI machines time.
configure({ asyncUtilTimeout: 5000 });

function signInAdmin() {
  mockStore.db.users["admin@example.com"] = {
    id: "00000000-0000-4000-8000-0000000000a9",
    org_id: "00000000-0000-4000-8000-0000000000b9",
    email: "admin@example.com",
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: null,
    profile_complete: true,
  };
  mockSignIn(mockStore, "admin@example.com");
}

function renderAt(path: string) {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

describe("overview (AD-2)", { timeout: 20_000 }, () => {
  it("is the default route, with the Operations nav group", async () => {
    signInAdmin();
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Overview", level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Admin" });
    expect(within(nav).getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/overview");
    const ops = within(nav).getByRole("list", { name: "Operations" });
    expect(within(ops).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Health",
      "Performance",
      "Errors",
      "Jobs",
      "Spend",
      "Controls",
    ]);
  });

  it("AO-1..AO-8: funnel, tiles with deltas, links, and not-measured metrics", async () => {
    signInAdmin();
    const user = renderAt("/overview?range=30d");
    expect(await screen.findByRole("heading", { name: "Funnel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Paid within 14 days")).toBeInTheDocument();
    expect(screen.getByText(/14\.3% of the step before/)).toBeInTheDocument();
    // AO-7: a number links to the list behind it.
    expect(screen.getByRole("link", { name: "1" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/interviews\?status=failed&from=/),
    );
    // Deltas against the previous period.
    expect(screen.getAllByText("+50% vs previous (2)").length).toBeGreaterThan(0);
    // AO-8: never hidden.
    const agreement = screen.getByText("Scorer agreement").closest(".kpi") as HTMLElement;
    expect(within(agreement).getByText("Not measured")).toBeInTheDocument();
    expect(within(agreement).getByText(/gold set/)).toBeInTheDocument();
    // L05: the post-session rating is measured.
    const realism = screen.getByText("Realism rating").closest(".kpi") as HTMLElement;
    expect(within(realism).getByText("4.30")).toBeInTheDocument();
    expect(screen.getByText("Model cost per day (UTC) by component")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "24 hours" }));
    expect(await screen.findByRole("button", { name: "24 hours" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("operations (OB-10..OB-14)", { timeout: 20_000 }, () => {
  it("OB-10: health tiles and host sparklines", async () => {
    signInAdmin();
    renderAt("/ops/health");
    const services = (await screen.findByRole("heading", { name: "Services" })).closest("section") as HTMLElement;
    const voice = within(services).getByText("Voice").closest("li") as HTMLElement;
    expect(voice).toHaveAttribute("data-status", "down");
    expect(within(voice).getByText("No heartbeat (OB-1)")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Disk (root), last 24 hours" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "61.0%" })).toBeInTheDocument();
  });

  it("OB-11: voice latency by component and the not-measured queue wait", async () => {
    signInAdmin();
    renderAt("/ops/performance");
    expect(await screen.findByRole("heading", { name: "Voice latency by component" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "llm ttft" })).toBeInTheDocument();
    expect(screen.getByText("Queue wait").closest(".kpi")).toHaveTextContent("Not measured");
  });

  it("OB-12: resolve an error group with a reason", async () => {
    signInAdmin();
    const user = renderAt("/ops/errors");
    await user.click(await screen.findByRole("button", { name: "TimeoutError" }));
    await user.click(await screen.findByRole("button", { name: "Mark resolved" }));
    const confirm = screen.getByRole("button", { name: "Resolve TimeoutError" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("Reason (saved in the audit log)"), "Raised the timeout");
    await user.click(confirm);
    // A resolved group leaves the open list.
    expect(await screen.findByText("No open error groups.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "resolved" }));
    expect(await screen.findByRole("button", { name: "KeyError" })).toBeInTheDocument();
    // The open group stays expanded.
    expect(await screen.findByText(/Resolved by admin@example.com/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reopen" })).toBeInTheDocument();
  });

  it("OB-13: retry a stuck scoring", async () => {
    signInAdmin();
    const user = renderAt("/ops/jobs");
    const scorings = await screen.findByRole("region", { name: "Scorings" });
    await user.click(within(scorings).getByRole("button", { name: "Retry" }));
    await user.type(within(scorings).getByLabelText("Reason (saved in the audit log)"), "Provider back up");
    await user.click(within(scorings).getByRole("button", { name: "Retry scoring for ana@example.com" }));
    expect(await within(scorings).findByText("None failed in the last 7 days or stuck now.")).toBeInTheDocument();
  });

  it("OB-14: spend against the cap and the hosted equivalent", async () => {
    signInAdmin();
    renderAt("/ops/spend");
    expect(await screen.findByText("Today vs cap")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Today's cost against the cap" })).toHaveAttribute("aria-valuenow", "16");
    expect(screen.getByText(/Not configured: set SHADOW_STT_USD_PER_SECOND/)).toBeInTheDocument();
    expect(screen.getByText(/Not tracked/)).toBeInTheDocument();
  });
});
