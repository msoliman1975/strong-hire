/**
 * Admin sign-in (D-1, first step of AA-2) and the AA-4 screen rule: only admins get past the
 * sign-in; anyone else sees "Page not found" and can sign out.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw/http";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { mockStore, server } from "../mocks/node";

function addUser(email: string, password: string) {
  const n = Object.keys(mockStore.db.users).length + 1;
  mockStore.db.users[email] = {
    id: `00000000-0000-4000-8000-00000000000${n}`,
    org_id: `00000000-0000-4000-8000-00000000001${n}`,
    email,
    auth_provider: "password",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    is_admin: false,
    full_name: null,
    profile_complete: true,
  };
  mockStore.db.passwords[email] = password;
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

describe("admin sign-in (D-1)", () => {
  it("sends a signed-out visitor to sign-in", async () => {
    renderAt("/interviews");
    expect(await screen.findByRole("heading", { name: "Admin sign-in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Admin" })).not.toBeInTheDocument();
  });

  it("signs an admin in with email and password and opens the Overview", async () => {
    addUser("admin@example.com", "correct horse battery");
    const user = renderAt("/signin");
    await user.type(await screen.findByLabelText("Email address"), "admin@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Overview", level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Admin" });
    // The first text node is the section name; a count badge (Alerts) may follow it.
    expect(within(nav).getAllByRole("link").map((a) => a.firstChild?.textContent)).toEqual([
      "Overview",
      "Interviews",
      "Users",
      "Alerts",
      "Health",
      "Performance",
      "Errors",
      "Jobs",
      "Spend",
      "Controls",
      "Audit log",
    ]);
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
    expect(await screen.findByTitle("Model profile on this server")).toHaveTextContent("fake");
  });

  it("shows the API's message for a wrong password", async () => {
    addUser("admin@example.com", "correct horse battery");
    const user = renderAt("/signin");
    await user.type(await screen.findByLabelText("Email address"), "admin@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("The email or password is wrong.")).toBeInTheDocument();
  });

  it("asks for an email link that returns to the admin app", async () => {
    let asked: string | null = null;
    server.use(
      http.post("*/api/auth/magic-link", ({ request }) => {
        asked = new URL(request.url).searchParams.get("app");
        return HttpResponse.json({ sent: true, dev_link: null }, { status: 202 });
      }),
    );
    const user = renderAt("/signin");
    await user.click(await screen.findByRole("button", { name: "Sign in with an email link instead" }));
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Email address"), "admin@example.com");
    await user.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
    expect(await screen.findByText(/a sign-in link is on its way/)).toBeInTheDocument();
    expect(asked).toBe("admin");
  });

  it("offers Google sign-in that returns to the admin app", async () => {
    renderAt("/signin");
    const google = await screen.findByRole("link", { name: "Sign in with Google" });
    expect(google).toHaveAttribute("href", expect.stringMatching(/\/api\/auth\/google\/login\?app=admin$/));
  });

  it("explains a link that did not work", async () => {
    renderAt("/signin?error=link_expired");
    expect(await screen.findByText("That link has expired. Ask for a new one.")).toBeInTheDocument();
  });

  it("AA-4: a signed-in candidate sees Page not found and can sign out", async () => {
    addUser("ana@example.com", "candidate password");
    const user = renderAt("/signin");
    await user.type(await screen.findByLabelText("Email address"), "ana@example.com");
    await user.type(screen.getByLabelText("Password"), "candidate password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Admin" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Admin sign-in" })).toBeInTheDocument();
    expect(mockStore.db.auth.status).toBe("signed_out");
  });

  it("AA-4: a pending candidate sign-up never reaches the admin pages", async () => {
    mockStore.db.auth = { status: "needs_signup", email: "new@example.com", userEmail: null };
    renderAt("/users");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Users" })).not.toBeInTheDocument();
  });

  it("signs an admin out", async () => {
    addUser("admin@example.com", "correct horse battery");
    mockStore.db.auth = { status: "signed_in", email: "admin@example.com", userEmail: "admin@example.com" };
    const user = renderAt("/audit");
    expect(await screen.findByRole("heading", { name: "Audit log" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Admin sign-in" })).toBeInTheDocument();
  });
});
