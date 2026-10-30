/**
 * U11: Profile with Strova (v2). PS-2: the plan style is shown and can be changed, and the change
 * reaches the plan on Home. PS-6: email reminders can be muted and unmuted.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { EMPTY_PROFILE } from "../mocks/handlers";
import { mockStore } from "../mocks/node";
import { setFeatureOverrides } from "../theme/features";

const EMAIL = "ana@example.com";

beforeEach(() => {
  setFeatureOverrides({ v2_enabled: true });
  globalThis.localStorage?.setItem("sh-tour-done-00000000-0000-4000-8000-0000000000a1", "x");
  mockStore.db.users[EMAIL] = {
    id: "00000000-0000-4000-8000-0000000000a1",
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email: EMAIL,
    auth_provider: "password",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email: EMAIL, userEmail: EMAIL };
  mockStore.db.profiles[EMAIL] = {
    ...EMPTY_PROFILE,
    full_name: "Ana Lopez",
    target_level: "senior",
    years_experience: 7,
    plan_style: "weekly",
    plan_email_muted: false,
  };
});
afterEach(() => setFeatureOverrides({}));

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

describe("Profile with Strova", () => {
  it("PS-2: shows the plan style and changes it at once; the account summary and details stay", async () => {
    const user = renderAt("/account/profile");
    expect(await screen.findByRole("heading", { level: 1, name: "Profile" })).toBeInTheDocument();
    const styles = screen.getByRole("group", { name: "Plan style" });
    const weekly = within(styles).getByRole("button", { name: /Weekly plan/ });
    const checklist = within(styles).getByRole("button", { name: /Readiness checklist/ });
    expect(weekly).toHaveAttribute("aria-pressed", "true");
    await user.click(checklist);
    await expect.poll(() => mockStore.db.profiles[EMAIL].plan_style).toBe("checklist");
    expect(await within(styles).findByRole("button", { name: /Readiness checklist/ })).toHaveAttribute("aria-pressed", "true");
    const account = screen.getByRole("region", { name: "Account" });
    expect(account).toHaveTextContent("Ana Lopez · ana@example.com · Senior · 7 years");
    expect(within(account).getByRole("link", { name: "Account" })).toHaveAttribute("href", "/account");
    expect(screen.getByRole("form", { name: "Profile" })).toBeInTheDocument();
  });

  it("PS-6: email reminders can be muted and unmuted; in the app they stay on", async () => {
    const user = renderAt("/account/profile");
    const reminders = await screen.findByRole("region", { name: "Reminders from Strova" });
    expect(reminders).toHaveTextContent("In the app");
    expect(within(reminders).getByText("On")).toBeInTheDocument();
    await user.click(within(reminders).getByRole("button", { name: "Mute email" }));
    await expect.poll(() => mockStore.db.profiles[EMAIL].plan_email_muted).toBe(true);
    expect(await within(reminders).findByText("Muted")).toBeInTheDocument();
    await user.click(within(reminders).getByRole("button", { name: "Unmute email" }));
    await expect.poll(() => mockStore.db.profiles[EMAIL].plan_email_muted).toBe(false);
  });

  it("FL-1: with v2 off the profile page keeps its v1 form", async () => {
    setFeatureOverrides({ v2_enabled: false });
    renderAt("/account/profile");
    expect(await screen.findByRole("heading", { level: 1, name: "Your profile" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Plan style" })).toBeNull();
  });
});
