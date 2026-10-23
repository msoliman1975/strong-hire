/**
 * Ops controls in the candidate app (OC-1 to OC-4): the site banner on every page, the paused
 * sign-up message, and the "temporarily unavailable" notice when new sessions are paused.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "./App";
import type { JobTargetOut } from "./api/types";
import { jobPosting } from "./mocks/fixtures";
import { mockStore, server } from "./mocks/node";
import { SessionSetupPage } from "./pages/SessionSetupPage";

const HOUR = 3600_000;

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

function setBanner(text: string, severity: "info" | "warning" | "critical", untilMs: number) {
  mockStore.db.siteStatus = {
    ...mockStore.db.siteStatus,
    banner: { text, severity, until: new Date(untilMs).toISOString() },
  };
}

describe("site banner (OC-4)", () => {
  it("shows the banner with its severity on the sign-in page", async () => {
    setBanner("Scoring is slow today.", "warning", Date.now() + HOUR);
    renderAt("/signin");
    const banner = await screen.findByRole("status", { name: "Site notice" }, { timeout: 4000 });
    expect(banner).toHaveTextContent("Scoring is slow today.");
    expect(banner).toHaveAttribute("data-severity", "warning");
  });

  it("a critical banner is an alert, on signed-in pages too", async () => {
    mockStore.db.users["ana@example.com"] = {
      id: "u1",
      org_id: "o1",
      email: "ana@example.com",
      auth_provider: "dev",
      training_consent: false,
      created_at: "2026-10-01T10:00:00Z",
      full_name: "Ana",
      profile_complete: true,
    };
    mockStore.db.auth = { status: "signed_in", email: "ana@example.com", userEmail: "ana@example.com" };
    setBanner("Voice interviews are down.", "critical", Date.now() + HOUR);
    renderAt("/reports");
    expect(await screen.findByRole("alert", { name: "Site notice" }, { timeout: 4000 })).toHaveTextContent("Voice interviews are down.");
  });

  it("is hidden after its end time", async () => {
    setBanner("Old news", "info", Date.now() - 1000);
    renderAt("/signin");
    expect(await screen.findByRole("tab", { name: "Sign in", selected: true }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText("Old news")).not.toBeInTheDocument();
  });

  it("shows nothing when there is no banner", async () => {
    renderAt("/signin");
    expect(await screen.findByRole("tab", { name: "Sign in", selected: true }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Site notice" })).not.toBeInTheDocument();
  });
});

describe("paused sign-ups (OC-1)", () => {
  it("the create-account tab says sign-ups are paused, and the API refusal is shown", async () => {
    mockStore.db.siteStatus = { ...mockStore.db.siteStatus, signups_open: false };
    const user = renderAt("/signin");
    await user.click(await screen.findByRole("tab", { name: "Create account" }, { timeout: 4000 }));
    expect(await screen.findByText(/We are not taking new sign-ups right now/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email address"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("join the waitlist");
    expect(mockStore.db.users["new@example.com"]).toBeUndefined();
  });

  it("an email link or Google sign-up comes back with the waitlist message", async () => {
    renderAt("/signin?error=signups_paused");
    expect(await screen.findByRole("alert", {}, { timeout: 4000 })).toHaveTextContent("We are not taking new sign-ups right now");
  });
});

const JOB: JobTargetOut = {
  id: "j1",
  name: "Software Engineer at Acme",
  deleted: false,
  status: "extracted",
  source_url: null,
  posting: jobPosting,
  level: "senior",
  company_id: null,
  company_slug: null,
  generic_mode: true,
  stage: null,
  context: { interviewer_name: null, interviewer_role: null, recruiter_notes: null, concerns: null },
  created_at: "2026-10-01T10:00:00Z",
  archived_at: null,
};

function renderSetup() {
  server.use(http.get("*/api/job-targets/:jobId", () => HttpResponse.json(JOB)));
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/jobs/j1/setup"]}>
        <Routes>
          <Route path="/jobs/:jobId/setup" element={<SessionSetupPage />} />
          <Route path="/sessions/:id/live" element={<p>live</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

describe("paused sessions (OC-2, OC-3)", () => {
  it("the setup page says interviews are unavailable and does not offer to start", async () => {
    mockStore.db.siteStatus = { ...mockStore.db.siteStatus, voice_sessions_open: false };
    renderSetup();
    expect(await screen.findByTestId("sessions-unavailable", {}, { timeout: 4000 })).toHaveTextContent("temporarily unavailable");
    expect(screen.getByRole("button", { name: "Start interview" })).toBeDisabled();
  });

  it("a refusal from the API (the spend cap) shows the friendly notice, not an error", async () => {
    server.use(
      http.post("*/api/sessions", () =>
        HttpResponse.json(
          {
            detail: {
              code: "spend_cap_reached",
              message: "New interviews are temporarily unavailable. Please try again in a little while.",
            },
          },
          { status: 503 },
        ),
      ),
    );
    const user = renderSetup();
    await user.click(await screen.findByRole("button", { name: "Start interview" }, { timeout: 4000 }));
    expect(await screen.findByTestId("sessions-unavailable", {}, { timeout: 4000 })).toHaveTextContent("Please try again in a little while.");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
