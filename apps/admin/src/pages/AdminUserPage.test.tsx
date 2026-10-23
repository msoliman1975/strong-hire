/**
 * Users and support pages (AU-1..AU-9) against the mocks: search, the user detail, and the
 * reason + confirm dialog on every action (AA-6, AA-7).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { configure, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { mockSignIn } from "../mocks/handlers";
import { mockStore } from "../mocks/node";

const ANA = "00000000-0000-4000-8000-0000000000a1";

// These tests type into several fields and wait for refetches; give slow CI machines room.
configure({ asyncUtilTimeout: 4000 });

function addUser(email: string, n: number, name: string | null) {
  mockStore.db.users[email] = {
    id: `00000000-0000-4000-8000-0000000000a${n}`,
    org_id: `00000000-0000-4000-8000-0000000000b${n}`,
    email,
    auth_provider: "password",
    training_consent: false,
    created_at: `2026-10-0${n}T10:00:00Z`,
    full_name: name,
    profile_complete: true,
  };
}

function seed() {
  addUser("ana@example.com", 1, "Ana Lopez");
  addUser("bo@example.com", 2, "Bo Chen");
  addUser("admin@example.com", 9, null);
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

describe("users and support", { timeout: 30_000 }, () => {
  it("AU-1: searches by name and filters by status", async () => {
    seed();
    const user = renderAt("/users");
    expect(await screen.findByRole("link", { name: "bo@example.com" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Search"), "ana lo");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("1 user")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "bo@example.com" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ana@example.com" })).toHaveAttribute("href", `/users/${ANA}`);

    await user.selectOptions(screen.getByLabelText("Status"), "suspended");
    expect(await screen.findByText("No users match.")).toBeInTheDocument();
  });

  it("AU-3, AA-7: a grant asks for an amount and a reason, repeats them, and shows on the user", async () => {
    seed();
    const user = renderAt(`/users/${ANA}`);
    expect(await screen.findByRole("heading", { name: "ana@example.com" })).toBeInTheDocument();
    expect(screen.getByText(/Metadata only/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Grant free interviews" }));
    const dialog = screen.getByRole("dialog", { name: "Grant free interviews" });
    const confirm = within(dialog).getByRole("button", { name: "Grant free interviews" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Free interviews"), "3");
    expect(within(dialog).getByText("3 extra free interviews")).toBeInTheDocument();
    expect(within(dialog).getByText("ana@example.com")).toBeInTheDocument();
    expect(confirm).toBeDisabled(); // no reason yet
    await user.type(within(dialog).getByLabelText(/Reason/), "beta tester");
    await user.click(confirm);

    expect(await screen.findByText("Done: 3 extra free interviews for ana@example.com.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const grants = screen.getByRole("heading", { name: "Grants" }).closest("section") as HTMLElement;
    expect(await within(grants).findByRole("cell", { name: "3 extra free interviews" })).toBeInTheDocument();
    expect(await screen.findByText("5 left of 5 (3 granted)")).toBeInTheDocument();

    // Revoke: a destructive confirm that repeats the grant and the user.
    await user.click(within(grants).getByRole("button", { name: "Revoke 3 extra free interviews" }));
    const revoke = screen.getByRole("dialog", { name: "Revoke grant" });
    expect(within(revoke).getByText("3 extra free interviews")).toBeInTheDocument();
    await user.type(within(revoke).getByLabelText(/Reason/), "given by mistake");
    await user.click(within(revoke).getByRole("button", { name: "Revoke grant" }));
    expect(await within(grants).findByText(/^Revoked/)).toBeInTheDocument();
  });

  it("AU-5: a comp plan needs an end date", async () => {
    seed();
    const user = renderAt(`/users/${ANA}`);
    await user.click(await screen.findByRole("button", { name: "Comp plan" }));
    const dialog = screen.getByRole("dialog", { name: "Give a comp plan" });
    await user.type(within(dialog).getByLabelText("Minute cap of the comp plan"), "120");
    await user.type(within(dialog).getByLabelText(/Reason/), "beta tester");
    const confirm = within(dialog).getByRole("button", { name: "Give a comp plan" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Paid access until/), "2099-01-31");
    expect(within(dialog).getByText(/until 2099-01-31/)).toBeInTheDocument();
    await user.click(confirm);
    expect(await screen.findByText(/Done: a comp plan with 120 minutes/)).toBeInTheDocument();
    expect(await screen.findByText(/120 left: 120 plan/)).toBeInTheDocument();
  });

  it("AU-7, AA-7: suspend repeats the email, then the user shows as suspended", async () => {
    seed();
    const user = renderAt(`/users/${ANA}`);
    await user.click(await screen.findByRole("button", { name: "Suspend" }));
    const dialog = screen.getByRole("dialog", { name: "Suspend user" });
    expect(within(dialog).getByText("ana@example.com")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Suspend" }));
    const again = screen.getByRole("dialog", { name: "Suspend user" });
    expect(within(again).getByLabelText(/Reason/)).toHaveValue(""); // a fresh reason each time
    await user.type(within(again).getByLabelText(/Reason/), "abuse report 7");
    await user.click(within(again).getByRole("button", { name: "Suspend ana@example.com" }));
    expect(await screen.findByText("ana@example.com is suspended.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Unsuspend" })).toBeInTheDocument();
    const audit = screen.getByRole("heading", { name: "Audit log" }).closest("section") as HTMLElement;
    expect(within(audit).getByRole("cell", { name: "user.suspended" })).toBeInTheDocument();
    expect(within(audit).getByRole("cell", { name: "abuse report 7" })).toBeInTheDocument();
  });

  it("AU-9: resend shows the rate limit error in the dialog", async () => {
    seed();
    const user = renderAt(`/users/${ANA}`);
    for (let i = 0; i < 4; i += 1) {
      await user.click(await screen.findByRole("button", { name: "Resend sign-in link" }));
      const dialog = screen.getByRole("dialog", { name: "Resend sign-in link" });
      await user.type(within(dialog).getByLabelText(/Reason/), "cannot sign in");
      await user.click(within(dialog).getByRole("button", { name: "Send link" }));
      if (i < 3) expect(await screen.findByText("Sign-in link sent to ana@example.com.")).toBeInTheDocument();
    }
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(/3 links were sent/);
  });
});
