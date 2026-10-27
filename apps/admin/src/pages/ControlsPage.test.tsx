/** Operations → Controls (OC-1 to OC-6, AA-7) against the admin mocks. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { activeControls, type OpsSettings } from "../api/controls";
import { MOCK_DEFAULTS, opsState } from "../mocks/controlsHandlers";
import { mockSignIn } from "../mocks/handlers";
import { mockStore } from "../mocks/node";

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

/** The Shell banner while a control is not at its default. */
async function opsBanner(): Promise<HTMLElement> {
  const label = await screen.findByText("Ops controls on:", {}, { timeout: 4000 });
  return label.parentElement as HTMLElement;
}

async function openControls() {
  signInAdmin();
  const user = renderAt("/ops/controls");
  expect(await screen.findByRole("heading", { name: "Controls", level: 1 })).toBeInTheDocument();
  await screen.findByRole("heading", { name: "Sign-ups (OC-1)" });
  return user;
}

describe("Controls page", () => {
  it("is in the admin nav, and every control starts at its default", async () => {
    await openControls();
    expect(within(screen.getByRole("navigation", { name: "Admin" })).getByRole("link", { name: "Controls" })).toHaveAttribute(
      "href",
      "/ops/controls",
    );
    expect(screen.getByText("Every control is at its default.")).toBeInTheDocument();
    expect(screen.queryByText(/Ops controls on:/)).not.toBeInTheDocument();
  });

  it("OC-1, AA-6: pausing sign-ups asks for a reason, and the Shell shows a banner", async () => {
    const user = await openControls();
    await user.click(screen.getByRole("button", { name: "Pause sign-ups" }));
    const dialog = screen.getByRole("dialog", { name: "Pause sign-ups" });
    const confirm = within(dialog).getByRole("button", { name: "Pause sign-ups" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), "beta is full");
    await user.click(confirm);
    expect(await opsBanner()).toHaveTextContent("Sign-ups paused");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText(/Last changed by admin@example.com/)).toBeInTheDocument();
    expect(opsState(mockStore.db).values.signups_paused).toBe(true);
  });

  it("AA-7, OC-2: pausing voice sessions needs the word PAUSE", async () => {
    const user = await openControls();
    await user.click(screen.getByRole("button", { name: "Pause voice" }));
    const dialog = screen.getByRole("dialog", { name: "Pause voice sessions" });
    const confirm = within(dialog).getByRole("button", { name: "Pause sessions" });
    await user.type(within(dialog).getByLabelText(/Reason/), "STT provider down");
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/to confirm/), "pause");
    expect(confirm).toBeDisabled();
    await user.clear(within(dialog).getByLabelText(/to confirm/));
    await user.type(within(dialog).getByLabelText(/to confirm/), "PAUSE");
    await user.click(confirm);
    expect(await opsBanner()).toHaveTextContent("Voice sessions paused");
    expect(screen.getByRole("button", { name: "Resume voice" })).toBeInTheDocument();
    expect(opsState(mockStore.db).values.sessions_paused_text).toBe(false);
  });

  it("a cancelled dialog changes nothing", async () => {
    const user = await openControls();
    await user.click(screen.getByRole("button", { name: "Pause text" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opsState(mockStore.db).values.sessions_paused_text).toBe(false);
  });

  it("OC-3: shows today's spend and changes the cap", async () => {
    const user = await openControls();
    expect(screen.getByText("$3.21")).toBeInTheDocument();
    const input = screen.getByLabelText("Cap in USD");
    await user.clear(input);
    await user.type(input, "40");
    await user.click(screen.getByRole("button", { name: "Save cap" }));
    const dialog = screen.getByRole("dialog", { name: "Change the daily spend cap" });
    expect(dialog).toHaveTextContent("$25.00 → $40.00");
    await user.type(within(dialog).getByLabelText(/Reason/), "launch day");
    await user.click(within(dialog).getByRole("button", { name: "Save cap" }));
    expect(await opsBanner()).toHaveTextContent("Spend cap $40.00");
    expect(opsState(mockStore.db).values.daily_spend_cap_usd).toBe(40);
  });

  it("OC-4: the banner editor previews the banner and saves it", async () => {
    const user = await openControls();
    await user.type(screen.getByLabelText("Text"), "Scoring is slow today.");
    await user.selectOptions(screen.getByLabelText("Severity"), "warning");
    const preview = screen.getByRole("note", { name: "Banner preview" });
    expect(preview).toHaveTextContent("Scoring is slow today.");
    expect(preview).toHaveAttribute("data-severity", "warning");
    await user.click(screen.getByRole("button", { name: "Show banner" }));
    const dialog = screen.getByRole("dialog", { name: "Show the site banner" });
    await user.type(within(dialog).getByLabelText(/Reason/), "provider incident");
    await user.click(within(dialog).getByRole("button", { name: "Show banner" }));
    expect(await opsBanner()).toHaveTextContent("Site banner shown");
    const saved = opsState(mockStore.db).values.site_banner;
    expect(saved?.text).toBe("Scoring is slow today.");
    expect(saved?.severity).toBe("warning");
    expect(Date.parse(saved?.until ?? "")).toBeGreaterThan(Date.now());
    expect(screen.getByRole("button", { name: "Remove banner" })).toBeInTheDocument();
  });

  it("OC-5: pauses job kinds with checkboxes", async () => {
    const user = await openControls();
    await user.click(screen.getByRole("checkbox", { name: "Scoring" }));
    await user.click(screen.getByRole("button", { name: "Save jobs" }));
    const dialog = screen.getByRole("dialog", { name: "Change paused jobs" });
    expect(dialog).toHaveTextContent("Paused: none → Scoring");
    await user.type(within(dialog).getByLabelText(/Reason/), "scorer model down");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await opsBanner()).toHaveTextContent("Scoring jobs paused");
    expect(opsState(mockStore.db).values.jobs_paused).toEqual(["scoring"]);
  });

  it("OC-6: shows the model profile and flags a mismatch", async () => {
    signInAdmin();
    const state = opsState(mockStore.db);
    state.models = {
      ...state.models,
      services: [
        { service: "voice", instance: "v1", model_profile: "hosted", version: "1.0", at: "2026-10-18T10:00:00Z" },
      ],
      mismatch: true,
    };
    renderAt("/ops/controls");
    expect(await screen.findByText("Services run different model profiles", { exact: false }, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText("fake-interviewer")).toBeInTheDocument();
    expect(screen.getByText("differs", { exact: false })).toBeInTheDocument();
  });

  it("CU-11: limits Custom interviews to paid plans with a reason, and opens them again", async () => {
    const user = await openControls();
    const panel = screen.getByRole("region", { name: "Custom interviews (CU-11)" });
    expect(within(panel).getByTestId("custom-access")).toHaveTextContent("Everyone");
    await user.click(within(panel).getByRole("button", { name: "Limit to paid plans" }));
    const dialog = screen.getByRole("dialog", { name: "Limit Custom to paid plans" });
    expect(dialog).toHaveTextContent("Custom interviews: Everyone → Paid plans only");
    const confirm = within(dialog).getByRole("button", { name: "Limit to paid plans" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), "launch: Custom is paid");
    await user.click(confirm);
    expect(await opsBanner()).toHaveTextContent("Custom interviews for paid plans only");
    expect(opsState(mockStore.db).values.custom_interview_access).toBe("paid_only");
    expect(within(panel).getByTestId("custom-access")).toHaveTextContent("Paid plans only");
    expect(within(panel).getByText(/Last changed by admin@example.com/)).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "Open to everyone" }));
    const back = screen.getByRole("dialog", { name: "Open Custom to everyone" });
    await user.type(within(back).getByLabelText(/Reason/), "beta test again");
    await user.click(within(back).getByRole("button", { name: "Open to everyone" }));
    await screen.findByText("Every control is at its default.");
    expect(opsState(mockStore.db).values.custom_interview_access).toBe("everyone");
  });

  it("FL-1, AA-6: turns the v2 screens on with a reason, and off again", async () => {
    const user = await openControls();
    const panel = screen.getByRole("region", { name: "v2 screens (FL-1)" });
    expect(within(panel).getByTestId("v2-state")).toHaveTextContent("Off");
    await user.click(within(panel).getByRole("button", { name: "Turn v2 on" }));
    const dialog = screen.getByRole("dialog", { name: "Turn the v2 screens on" });
    expect(dialog).toHaveTextContent("v2 screens: Off → On");
    const confirm = within(dialog).getByRole("button", { name: "Turn v2 on" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), "launch v2.0");
    await user.click(confirm);
    expect(await opsBanner()).toHaveTextContent("v2 screens on");
    expect(opsState(mockStore.db).values.v2_enabled).toBe(true);
    expect(within(panel).getByTestId("v2-state")).toHaveTextContent("On");
    expect(within(panel).getByText(/Last changed by admin@example.com/)).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "Turn v2 off" }));
    const back = screen.getByRole("dialog", { name: "Turn the v2 screens off" });
    await user.type(within(back).getByLabelText(/Reason/), "roll back");
    await user.click(within(back).getByRole("button", { name: "Turn v2 off" }));
    await screen.findByText("Every control is at its default.");
    expect(opsState(mockStore.db).values.v2_enabled).toBe(false);
  });

  it("the Shell banner shows on other pages too", async () => {
    signInAdmin();
    opsState(mockStore.db).values = { ...MOCK_DEFAULTS, sessions_paused_text: true };
    renderAt("/audit");
    expect(await opsBanner()).toHaveTextContent("Text sessions paused");
  });
});

describe("activeControls", () => {
  const base: OpsSettings = {
    values: { ...MOCK_DEFAULTS },
    defaults: MOCK_DEFAULTS,
    meta: [],
    spend_today_usd: 0,
  };

  it("lists nothing at the defaults, and an ended banner is not shown", () => {
    expect(activeControls(base)).toEqual([]);
    const ended = {
      ...base,
      values: { ...MOCK_DEFAULTS, site_banner: { text: "x", severity: "info" as const, until: "2000-01-01T00:00:00Z" } },
    };
    expect(activeControls(ended)).toEqual([]);
  });

  it("OC-3: says when the spend cap is reached", () => {
    expect(activeControls({ ...base, spend_today_usd: 25 })).toEqual(["Spend cap reached: new sessions refused"]);
  });
});
