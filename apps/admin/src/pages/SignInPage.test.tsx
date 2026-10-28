/**
 * Admin sign-in (AA-2) through the admin routes, and the AA-4 screen rule: without a live admin
 * session the app shows sign-in. Only admins (db.admins) can get a session.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw/http";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { mockLinkToken, mockSignIn } from "../mocks/handlers";
import { mockStore, server } from "../mocks/node";

const PASSWORD = "correct horse battery";

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

async function typeCredentials(user: ReturnType<typeof userEvent.setup>, email: string, password: string) {
  await user.type(await screen.findByLabelText("Email address"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("admin sign-in (AA-2)", () => {
  it("AA-4: sends a visitor without an admin session to sign-in", async () => {
    renderAt("/interviews");
    expect(await screen.findByRole("heading", { name: "Admin sign-in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Admin" })).not.toBeInTheDocument();
  });

  it("signs an admin in with email and password and opens the Overview", async () => {
    mockStore.db.passwords["admin@example.com"] = PASSWORD;
    const user = renderAt("/signin");
    await typeCredentials(user, "admin@example.com", PASSWORD);
    expect(await screen.findByRole("heading", { name: "Overview", level: 1 })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Admin" });
    // The first text node is the section name; a count badge (Alerts) may follow it.
    expect(within(nav).getAllByRole("link").map((a) => a.firstChild?.textContent)).toEqual([
      "Overview",
      "Plan usage",
      "Story library",
      "Coach",
      "Readiness",
      "Interviews",
      "Simulations",
      "Users",
      "Waitlist",
      "Alerts",
      "Health",
      "Performance",
      "Errors",
      "Jobs",
      "Spend",
      "Controls",
      "Companies",
      "Company requests",
      "Auto-profiles",
      "Audit log",
      "Admins",
      "My sessions",
    ]);
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
    expect(await screen.findByTitle("Model profile on this server")).toHaveTextContent("fake");
  });

  it("shows the API's message for a wrong password, or for someone who is not an admin", async () => {
    mockStore.db.passwords["admin@example.com"] = PASSWORD;
    mockStore.db.passwords["ana@example.com"] = PASSWORD;
    const user = renderAt("/signin");
    await typeCredentials(user, "admin@example.com", "wrong");
    expect(await screen.findByText("The email or password is wrong.")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Email address"));
    await user.clear(screen.getByLabelText("Password"));
    await typeCredentials(user, "ana@example.com", PASSWORD);
    expect(await screen.findByText("The email or password is wrong.")).toBeInTheDocument();
    expect(mockStore.db.signedIn).toBeNull();
  });

  it("asks the admin routes for an email link, with the same answer for everyone", async () => {
    let asked: string | null = null;
    server.use(
      http.post("*/api/admin/auth/link", async ({ request }) => {
        asked = ((await request.json()) as { email: string }).email;
        return HttpResponse.json({ sent: true, dev_link: null }, { status: 202 });
      }),
    );
    const user = renderAt("/signin");
    await user.click(await screen.findByRole("button", { name: "Sign in with an email link instead" }));
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Email address"), "admin@example.com");
    await user.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
    expect(await screen.findByText(/a sign-in link is on its way/)).toBeInTheDocument();
    expect(asked).toBe("admin@example.com");
  });

  it("signs in from the email link page", async () => {
    renderAt(`/signin/verify?token=${encodeURIComponent(mockLinkToken("admin@example.com"))}`);
    expect(await screen.findByRole("heading", { name: "Overview", level: 1 })).toBeInTheDocument();
    expect(mockStore.db.signedIn).not.toBeNull();
  });

  it("explains an email link that did not work", async () => {
    renderAt("/signin/verify?token=bad");
    expect(await screen.findByText("That link is not valid. Ask for a new one.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to sign-in" })).toHaveAttribute("href", "/signin");
  });

  it("offers Google sign-in through the admin routes", async () => {
    renderAt("/signin");
    const google = await screen.findByRole("link", { name: "Sign in with Google" });
    expect(google).toHaveAttribute("href", expect.stringMatching(/\/api\/admin\/auth\/google\/login$/));
  });

  it("explains a Google account that is not an admin", async () => {
    renderAt("/signin?error=not_admin");
    expect(await screen.findByText("That Google account may not use the admin app.")).toBeInTheDocument();
  });

  it("signs an admin out", async () => {
    mockSignIn(mockStore, "admin@example.com");
    const user = renderAt("/audit");
    expect(await screen.findByRole("heading", { name: "Audit log" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Admin sign-in" })).toBeInTheDocument();
    expect(mockStore.db.signedIn).toBeNull();
  });
});
