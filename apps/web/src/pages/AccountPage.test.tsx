/**
 * Account page against the mocks of the real P9 endpoints. Requirement IDs: AC-2 (consent toggle),
 * AC-1 (export and delete), BL-1 (plan, minutes and cancellation with the exit survey).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { refreshUsage } from "../mocks/handlers";
import { mockStore, server } from "../mocks/node";

function signedIn(email = "ana@example.com") {
  mockStore.db.users[email] = {
    id: "00000000-0000-4000-8000-0000000000a1",
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email,
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
}

function paid(minutesUsed = 120) {
  mockStore.db.usage = refreshUsage({
    ...mockStore.db.usage,
    plan: "paid",
    status: "active",
    minutes_used: minutesUsed,
    minutes_cap: 300,
    period_start: "2026-10-01T00:00:00Z",
    period_end: "2026-11-01T00:00:00Z",
    free_interviews_left: 0,
    has_billing_account: true,
  });
}

function renderAccount() {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/account"]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

describe("account page", () => {
  it("BL-2: a free user sees the free interviews left from the API", async () => {
    signedIn();
    mockStore.db.usage = refreshUsage({ ...mockStore.db.usage, free_interviews_total: 2, free_interviews_left: 2 });
    renderAccount();
    expect(await screen.findByText(/Free plan\. 2 of 2 free interviews left\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See the monthly plan" })).toHaveAttribute("href", "/upgrade");
    expect(screen.queryByRole("button", { name: "Cancel plan" })).not.toBeInTheDocument();
  });

  it("BL-1: a paid user sees minutes and the renewal date, and cancels with the exit survey", async () => {
    signedIn();
    paid(120);
    const user = renderAccount();
    expect(await screen.findByText("120 of 300 used, 180 left")).toBeInTheDocument();
    expect(screen.getByText("Renews on")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel plan" }));
    expect(screen.getByRole("heading", { name: "Before you go" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue to cancel" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Answer both questions, or skip the survey.");
    expect(mockStore.db.exitSurveys).toEqual([]);

    const sent: string[] = [];
    server.events.on("request:start", ({ request }) => {
      sent.push(`${request.method} ${new URL(request.url).pathname}`);
    });
    await user.click(screen.getByRole("radio", { name: "I got the job" }));
    await user.click(screen.getByRole("radio", { name: "Yes" }));
    await user.type(screen.getByLabelText("Anything else? (optional)"), "Thank you");
    await user.click(screen.getByRole("button", { name: "Continue to cancel" }));

    await waitFor(() => expect(mockStore.db.usage.cancel_at_period_end).toBe(true));
    expect(mockStore.db.exitSurveys).toEqual([
      { reason: "got_the_job", got_job: "yes", reason_detail: "Thank you" },
    ]);
    // The survey is saved first, then the portal opens at the cancellation step.
    expect(sent.filter((r) => r.includes("/billing/"))).toEqual(
      expect.arrayContaining(["POST /api/billing/exit-survey", "POST /api/billing/portal"]),
    );
  });

  it("AC-1: export becomes a one-time download link", async () => {
    signedIn();
    const user = renderAccount();
    await user.click(await screen.findByRole("button", { name: "Prepare export" }));
    const link = await screen.findByRole("link", { name: "Download export" });
    expect(link).toHaveAttribute("download", "strong-hire-export.zip");
  });

  it("AC-2: the consent switch saves the new value", async () => {
    signedIn();
    const user = renderAccount();
    const toggle = await screen.findByRole("switch", { name: "Use my transcripts to improve Strong Hire" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await user.click(toggle);
    expect(await screen.findByText("Saved. Training-data use is on.")).toBeInTheDocument();
    expect(mockStore.db.users["ana@example.com"].training_consent).toBe(true);
  });
});
