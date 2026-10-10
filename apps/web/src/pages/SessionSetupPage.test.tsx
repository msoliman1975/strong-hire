/**
 * Session setup durations (IV-7) and the free plan (BL-2): free accounts get 10-minute mini
 * interviews only; a paid plan may pick 10, 30 or 45 minutes.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router";
import { describe, expect, it } from "vitest";

import type { CreateSessionRequest, JobTargetOut, Usage } from "../api/types";
import { createQueryClient } from "../App";
import { FREE_USAGE } from "../mocks/db";
import { jobPosting } from "../mocks/fixtures";
import { server } from "../mocks/node";
import { PaywallPage } from "./PaywallPage";
import { SessionSetupPage } from "./SessionSetupPage";

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

const PAID: Usage = {
  ...FREE_USAGE,
  plan: "paid",
  status: "active",
  minutes_cap: 300,
  minutes_left: 300,
  free_interviews_left: 0,
  full_interviews_allowed: true,
};

function Upgrade() {
  const [params] = useSearchParams();
  return <p data-testid="upgrade-reason">{params.get("reason")}</p>;
}

function renderSetup(usage: Usage, paywall = false) {
  const bodies: CreateSessionRequest[] = [];
  server.use(
    http.get("*/api/job-targets/:jobId", () => HttpResponse.json(JOB)),
    http.get("*/api/billing/usage", () => HttpResponse.json(usage)),
    http.post("*/api/sessions", async ({ request }) => {
      const body = (await request.json()) as CreateSessionRequest;
      bodies.push(body);
      return HttpResponse.json(
        {
          detail: {
            code: "full_interview_requires_plan",
            message: "Full interviews are part of the subscription. Free accounts get 2 mini interviews.",
            upgrade_url: "/upgrade",
          },
        },
        { status: 402 },
      );
    }),
  );
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/jobs/j1/setup"]}>
        <Routes>
          <Route path="/jobs/:jobId/setup" element={<SessionSetupPage />} />
          <Route path="/upgrade" element={paywall ? <PaywallPage /> : <Upgrade />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { user, bodies };
}

describe("session setup durations", () => {
  it("a free account gets the mini preselected and cannot pick 30 or 45 minutes", async () => {
    const { user, bodies } = renderSetup(FREE_USAGE);
    const mini = await screen.findByRole("radio", { name: /^10 minutes \(mini\)/ });
    expect(mini).toBeChecked();
    expect(mini).toBeEnabled();
    expect(screen.getByRole("radio", { name: /^30 minutes/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /^45 minutes/ })).toBeDisabled();
    expect(
      await screen.findByText(/Full interviews \(30 and 45 minutes\) need a subscription\. Free accounts get 2 mini/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start interview" }));
    expect(await screen.findByTestId("upgrade-reason")).toBeInTheDocument();
    expect(bodies[0].config.duration_min).toBe(10);
  });

  it("a paid account can pick any length, and 30 minutes is the default", async () => {
    const { user, bodies } = renderSetup(PAID);
    expect(await screen.findAllByText("A full interview.")).toHaveLength(2); // usage is loaded
    const full = screen.getByRole("radio", { name: /^30 minutes/ });
    expect(full).toBeChecked();
    expect(full).toBeEnabled();
    expect(screen.getByRole("radio", { name: /^45 minutes/ })).toBeEnabled();
    expect(screen.queryByText(/need a subscription/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /^10 minutes \(mini\)/ }));
    await user.click(screen.getByRole("button", { name: "Start interview" }));
    await screen.findByTestId("upgrade-reason");
    expect(bodies[0].config.duration_min).toBe(10);
  });

  it("IV-8: Coach mode is chosen first, so the controls show unless the candidate picks Realistic", async () => {
    const { user, bodies } = renderSetup(PAID);
    expect(await screen.findByRole("radio", { name: /^Coach/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Start interview" }));
    await screen.findByTestId("upgrade-reason");
    expect(bodies[0].config.mode).toBe("coach");
  });

  it("the paywall explains the full_interview_requires_plan reason", async () => {
    const { user } = renderSetup(FREE_USAGE, true);
    await screen.findByRole("radio", { name: /^10 minutes \(mini\)/ });
    await user.click(screen.getByRole("button", { name: "Start interview" }));
    expect(
      await screen.findByText(/Full interviews \(30 and 45 minutes\) are part of the subscription\./),
    ).toBeInTheDocument();
  });
});
