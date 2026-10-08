/**
 * Admin area (R2) against the admin mocks: only admins see it; transcript and traces need the
 * user's consent; each view adds audit entries.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../../App";
import type { SessionRecord } from "../../api/types";
import { mockStore } from "../../mocks/node";

const SESSION_ID = "00000000-0000-4000-8000-0000000000c1";

function addUser(email: string, isAdmin: boolean, consent = false) {
  mockStore.db.users[email] = {
    id: isAdmin ? "00000000-0000-4000-8000-0000000000a9" : "00000000-0000-4000-8000-0000000000a1",
    org_id: isAdmin ? "00000000-0000-4000-8000-0000000000b9" : "00000000-0000-4000-8000-0000000000b1",
    email,
    auth_provider: "dev",
    training_consent: consent,
    created_at: "2026-10-01T10:00:00Z",
    is_admin: isAdmin,
  };
}

function seed({ consent = false, signedInAs = "admin@example.com" } = {}) {
  addUser("ana@example.com", false, consent);
  addUser("admin@example.com", true);
  const session: SessionRecord = {
    id: SESSION_ID,
    job_target_id: "00000000-0000-4000-8000-0000000000d1",
    config: {
      interview_type: "behavioral",
      difficulty: "realistic",
      mode: "realistic",
      duration_min: 10,
      level: "senior",
    },
    channel: "voice",
    brief_ready: true,
    status: "completed",
    started_at: "2026-10-07T09:00:00Z",
    ended_at: "2026-10-07T09:09:30Z",
    minutes_billed: 10,
  };
  mockStore.db.sessions.push(session);
  mockStore.db.auth = { status: "signed_in", email: signedInAs, userEmail: signedInAs };
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

describe("admin area (R2)", () => {
  it("is hidden from users who are not admins", async () => {
    seed({ signedInAs: "ana@example.com" });
    renderAt("/admin/interviews");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  });

  it("lists interviews with cost and a daily total, and shows the Admin link", async () => {
    seed();
    renderAt("/admin");
    expect(await screen.findByRole("heading", { name: "Interviews" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin");
    const daily = (await screen.findByRole("heading", { name: "Cost per day" })).closest("section");
    expect(daily).not.toBeNull();
    expect(within(daily as HTMLElement).getByRole("cell", { name: "2026-10-07" })).toBeInTheDocument();
    expect(within(daily as HTMLElement).getAllByText("$0.0123")).toHaveLength(2); // the day and the total
    expect(screen.getByRole("cell", { name: /^ana@example.com/ })).toBeInTheDocument();
    expect(screen.getByText("(no consent)")).toBeInTheDocument();
  });

  it("shows metadata only when the user has no consent, and writes no audit entry", async () => {
    seed({ consent: false });
    const user = renderAt(`/admin/interviews/${SESSION_ID}`);
    expect(await screen.findByText("This user has not given consent. You can see the details above only.")).toBeInTheDocument();
    expect(screen.getByText("Lean Hire")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Transcript" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Interviewer reasoning" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Audit log" }));
    expect(await screen.findByText("No entries yet.")).toBeInTheDocument();
  });

  it("shows the transcript and the traces with consent, and audits the view", async () => {
    seed({ consent: true });
    const user = renderAt(`/admin/interviews/${SESSION_ID}`);
    expect(await screen.findByRole("heading", { name: "Transcript" })).toBeInTheDocument();
    expect(screen.getByText("Happy to be here.")).toBeInTheDocument();
    const traces = screen.getByRole("heading", { name: "Interviewer reasoning" }).closest("section") as HTMLElement;
    expect(within(traces).getByRole("heading", { name: "4. probe (say)" })).toBeInTheDocument();
    expect(within(traces).getByText("model chose probe; model said probe (missing: measurable result)")).toBeInTheDocument();
    expect(within(traces).getByRole("heading", { name: "5. take your time (line)" })).toBeInTheDocument();
    await user.click(within(traces).getAllByText("Prompt (2 messages)")[0]);
    expect(within(traces).getAllByText("You are Alex, a job interviewer.")[0]).toBeVisible();

    await user.click(screen.getByRole("link", { name: "Audit log" }));
    expect(await screen.findByRole("cell", { name: "admin.transcript_viewed" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "admin.traces_viewed" })).toBeInTheDocument();
    expect(screen.getAllByRole("cell", { name: "admin@example.com" })).toHaveLength(2);
  });

  it("lists users with plan, consent and interviews", async () => {
    seed({ consent: true });
    renderAt("/admin/users");
    const row = (await screen.findByRole("link", { name: "ana@example.com" })).closest("tr") as HTMLElement;
    expect(within(row).getByRole("cell", { name: "Yes" })).toBeInTheDocument();
    expect(within(row).getByRole("cell", { name: "1" })).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "ana@example.com" })).toHaveAttribute(
      "href",
      "/admin/interviews?user=00000000-0000-4000-8000-0000000000a1",
    );
  });
});
