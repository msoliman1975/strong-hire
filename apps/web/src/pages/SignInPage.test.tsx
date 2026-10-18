/**
 * Sign-in page, against the MSW mock API. Requirement IDs: AC-4 (email and password sign-up and
 * sign-in, magic link kept as a second way), AC-5 (forgot password and reset).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { API_BASE } from "../api/client";
import { server } from "../mocks/node";

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

function recordBodies(path: string): unknown[] {
  const bodies: unknown[] = [];
  server.events.on("request:start", async ({ request }) => {
    if (request.url.endsWith(path)) bodies.push(await request.clone().json());
  });
  return bodies;
}

describe("sign-in page", () => {
  it("shows the practice loop next to the form", async () => {
    renderAt("/signin");
    expect(await screen.findByRole("tab", { name: "Sign in", selected: true })).toBeInTheDocument();
    const stage = screen.getByRole("complementary", { name: "How practice works" });
    expect(stage).toHaveTextContent("Practice until it reads Strong Hire.");
    expect(stage).toHaveTextContent("Get Strong Hire");
  });

  it("AC-4: a new account needs a valid email, an 8-character password and the 18+ confirmation", async () => {
    const bodies = recordBodies("/api/auth/password/signup");
    const user = renderAt("/signin");
    await user.click(await screen.findByRole("tab", { name: "Create account" }));
    expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email address"), "not-an-email");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText("Enter an email address, for example name@example.com.")).toBeInTheDocument();
    expect(screen.getByText("Use at least 8 characters.")).toBeInTheDocument();
    expect(screen.getByText("Confirm that you are 18 or older and accept the terms.")).toBeInTheDocument();
    expect(bodies).toEqual([]);
  });

  it("AC-4: sign-up signs in at once, and the password works before the email is confirmed", async () => {
    const bodies = recordBodies("/api/auth/password/signup");
    const user = renderAt("/signin");
    await user.click(await screen.findByRole("tab", { name: "Create account" }));
    await user.type(screen.getByLabelText("Email address"), "ana@example.com");
    await user.type(screen.getByLabelText("Your name (optional)"), "Ana Lopez");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByLabelText(/I am 18 or older, and I accept/));
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: "Tell us about yourself" })).toBeInTheDocument();
    expect(bodies).toEqual([
      {
        email: "ana@example.com",
        password: "correct horse battery",
        full_name: "Ana Lopez",
        age_confirmed: true,
        terms_accepted: true,
        training_consent: false,
      },
    ]);
  });

  it("AC-4: a wrong password is refused, the right one signs in", async () => {
    const signup = renderAt("/signin?mode=signup");
    await signup.type(await screen.findByLabelText("Email address"), "dee@example.com");
    await signup.type(screen.getByLabelText("Password"), "correct horse battery");
    await signup.click(screen.getByLabelText(/I am 18 or older, and I accept/));
    await signup.click(screen.getByRole("button", { name: "Create account" }));
    await screen.findByRole("heading", { name: "Tell us about yourself" });
    await fetch(`${API_BASE}/auth/logout`, { method: "POST" });
    document.body.innerHTML = "";

    const user = renderAt("/signin");
    await user.type(await screen.findByLabelText("Email address"), "dee@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong password!!");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("The email or password is wrong.")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Tell us about yourself" })).toBeInTheDocument();
  });

  it("AC-4: an email that already has an account cannot sign up again", async () => {
    const first = renderAt("/signin?mode=signup");
    await first.type(await screen.findByLabelText("Email address"), "eve@example.com");
    await first.type(screen.getByLabelText("Password"), "first password");
    await first.click(screen.getByLabelText(/I am 18 or older, and I accept/));
    await first.click(screen.getByRole("button", { name: "Create account" }));
    await screen.findByRole("heading", { name: "Tell us about yourself" });
    await fetch(`${API_BASE}/auth/logout`, { method: "POST" });
    document.body.innerHTML = "";

    const user = renderAt("/signin?mode=signup");
    await user.type(await screen.findByLabelText("Email address"), "eve@example.com");
    await user.type(screen.getByLabelText("Password"), "other password");
    await user.click(screen.getByLabelText(/I am 18 or older, and I accept/));
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("An account with this email already exists.");
  });

  it("AC-4: the password can be shown, and new-password rules update as the user types", async () => {
    const user = renderAt("/signin?mode=signup");
    const field = await screen.findByLabelText("Password");
    expect(field).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(field).toHaveAttribute("type", "text");
    await user.type(screen.getByLabelText("Email address"), "ana@example.com");
    await user.type(field, "ana-is-twelve-chars");
    expect(screen.getByText("8+ characters").closest("li")).toHaveAttribute("data-met", "true");
    expect(screen.getByText("Not your email").closest("li")).toHaveAttribute("data-met", "false");
  });

  it("AC-4: the magic link stays as a second way to sign in", async () => {
    const bodies = recordBodies("/api/auth/magic-link");
    const user = renderAt("/signin");
    await user.click(await screen.findByRole("button", { name: "Email me a sign-in link instead" }));
    expect(screen.getByRole("heading", { name: "Email me a sign-in link" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email address"), "bo@example.com");
    await user.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
    expect(await screen.findByText(/We sent a sign-in link to/)).toBeInTheDocument();
    expect(bodies).toEqual([{ email: "bo@example.com" }]);
  });

  it("AC-5: forgot password asks for the email and says the same thing for any email", async () => {
    const bodies = recordBodies("/api/auth/password/forgot");
    const user = renderAt("/signin");
    await user.click(await screen.findByRole("button", { name: "Forgot password?" }));
    expect(screen.getByRole("heading", { name: "Reset your password" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email address"), "nobody@example.com");
    await user.click(screen.getByRole("button", { name: "Email me a reset link" }));
    expect(await screen.findByText(/If/)).toHaveTextContent(
      "If nobody@example.com has a Strong Hire account, we sent it a link to choose a new password.",
    );
    expect(bodies).toEqual([{ email: "nobody@example.com" }]);
  });

  it("AC-5: the reset page sets a new password", async () => {
    // Make an account first, through the mock sign-up.
    const signup = renderAt("/signin?mode=signup");
    await signup.type(await screen.findByLabelText("Email address"), "cy@example.com");
    await signup.type(screen.getByLabelText("Password"), "first long secret");
    await signup.click(screen.getByLabelText(/I am 18 or older, and I accept/));
    await signup.click(screen.getByRole("button", { name: "Create account" }));
    await screen.findByRole("heading", { name: "Tell us about yourself" });
    await fetch(`${API_BASE}/auth/logout`, { method: "POST" });
    document.body.innerHTML = "";

    const bodies = recordBodies("/api/auth/password/reset");
    const user = renderAt("/reset-password?token=cy@example.com");
    expect(await screen.findByRole("heading", { name: "Choose a new password" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("New password"), "short");
    await user.click(screen.getByRole("button", { name: "Save password and sign in" }));
    expect(screen.getByText("Use at least 8 characters.")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("New password"));
    await user.type(screen.getByLabelText("New password"), "second long secret");
    await user.click(screen.getByRole("button", { name: "Save password and sign in" }));
    expect(await screen.findByRole("heading", { name: "Tell us about yourself" })).toBeInTheDocument();
    expect(bodies).toEqual([{ token: "cy@example.com", password: "second long secret" }]);
  });

  it("AC-5: the reset page without a token explains what to do", async () => {
    renderAt("/reset-password");
    expect(await screen.findByRole("alert")).toHaveTextContent("This page needs the link from the reset email.");
  });
});
