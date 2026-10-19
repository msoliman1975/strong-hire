/**
 * Settings (AA-1, AA-8): Admins (list, add, remove with a reason) and My sessions (list, revoke).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { auditLog } from "../mocks/adminHandlers";
import { mockAdmin } from "../mocks/db";
import { mockSignIn } from "../mocks/handlers";
import { mockStore } from "../mocks/node";

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

describe("Settings > Admins (AA-1)", () => {
  it("lists admins and opens from the Settings nav", async () => {
    mockStore.db.admins.push(mockAdmin("ops@example.com", 2, "admin@example.com"));
    mockSignIn(mockStore, "admin@example.com");
    const user = renderAt("/interviews");
    await user.click(await screen.findByRole("link", { name: "Admins" }));
    expect(await screen.findByRole("heading", { name: "Admins" })).toBeInTheDocument();
    const me = screen.getByRole("cell", { name: /^admin@example.coms*You$/ }).closest("tr") as HTMLElement;
    expect(within(me).getByText("You")).toBeInTheDocument();
    expect(within(me).queryByRole("button")).not.toBeInTheDocument(); // cannot remove yourself
    const ops = screen.getByRole("cell", { name: "ops@example.com" }).closest("tr") as HTMLElement;
    expect(within(ops).getByRole("cell", { name: "Active" })).toBeInTheDocument();
  });

  it("adds an admin with a reason, and audits it", async () => {
    mockSignIn(mockStore, "admin@example.com");
    const user = renderAt("/settings/admins");
    await user.type(await screen.findByLabelText("Email address"), "New@Example.com");
    await user.click(screen.getByRole("button", { name: "Add admin" }));
    const dialog = screen.getByRole("dialog", { name: "Add an admin" });
    const confirm = within(dialog).getByRole("button", { name: "Add new@example.com" });
    expect(confirm).toBeDisabled(); // AA-6: the reason is required
    await user.type(within(dialog).getByLabelText(/Reason/), "joins on-call");
    await user.click(confirm);
    expect(await screen.findByText("new@example.com is now an admin.")).toBeInTheDocument();
    expect(await screen.findByRole("cell", { name: "new@example.com" })).toBeInTheDocument();
    expect(auditLog(mockStore.db)[0]).toMatchObject({
      action: "admin.admin_added",
      actor: "admin@example.com",
      details: { reason: "joins on-call" },
    });
  });

  it("removes an admin after a confirmation that repeats the email (AA-7, AA-8)", async () => {
    mockStore.db.admins.push(mockAdmin("ops@example.com", 2, "admin@example.com"));
    mockSignIn(mockStore, "ops@example.com");
    mockSignIn(mockStore, "admin@example.com");
    const user = renderAt("/settings/admins");
    await user.click(await screen.findByRole("button", { name: "Remove ops@example.com" }));
    const dialog = screen.getByRole("dialog", { name: "Remove an admin" });
    expect(within(dialog).getByText(/1 live session end now/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Reason/), "left the team");
    await user.click(within(dialog).getByRole("button", { name: "Remove ops@example.com" }));
    expect(await screen.findByText("ops@example.com was removed and signed out.")).toBeInTheDocument();
    expect(mockStore.db.adminSessions.filter((s) => s.email === "ops@example.com" && !s.revoked)).toEqual([]);
    expect(await screen.findByRole("cell", { name: /^Removed / })).toBeInTheDocument();
  });

  it("closes the dialog on Cancel without a change", async () => {
    mockStore.db.admins.push(mockAdmin("ops@example.com", 2, "admin@example.com"));
    mockSignIn(mockStore, "admin@example.com");
    const user = renderAt("/settings/admins");
    await user.click(await screen.findByRole("button", { name: "Remove ops@example.com" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mockStore.db.admins.find((a) => a.email === "ops@example.com")?.disabled_at).toBeNull();
  });
});

describe("Settings > My sessions (AA-8)", () => {
  it("lists my sessions and revokes another one", async () => {
    mockSignIn(mockStore, "admin@example.com");
    const other = mockStore.db.signedIn;
    mockSignIn(mockStore, "admin@example.com");
    const user = renderAt("/settings/sessions");
    expect(await screen.findByRole("heading", { name: "My sessions" })).toBeInTheDocument();
    expect(await screen.findByText("This browser")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    await screen.findByRole("button", { name: "Sign out here" });
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
    expect(mockStore.db.adminSessions.find((s) => s.id === other)?.revoked).toBe(true);
  });

  it("revoking this browser's session signs me out", async () => {
    mockSignIn(mockStore, "admin@example.com");
    const user = renderAt("/settings/sessions");
    await user.click(await screen.findByRole("button", { name: "Sign out here" }));
    expect(await screen.findByRole("heading", { name: "Admin sign-in" })).toBeInTheDocument();
    expect(mockStore.db.signedIn).toBeNull();
  });
});
