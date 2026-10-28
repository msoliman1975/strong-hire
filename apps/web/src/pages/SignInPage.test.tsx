/**
 * Sign-in page, against the MSW mock API. Requirement IDs: AC-4 (email and password sign-up and
 * sign-in, refused until the email is confirmed; magic link kept as a second way), AC-5 (forgot
 * password and reset).
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

/** AC-4: open the confirmation link (in the mock, its token is the email). */
async function confirmEmail(email: string) {
  await fetch(`${API_BASE}/auth/password/confirm?token=${encodeURIComponent(email)}`);
}

/** Sign up through the form; the page then asks the user to check their inbox. */
async function signUp(email: string, password: string) {
  const user = renderAt("/signin?mode=signup");
  await user.type(await screen.findByLabelText("Email address"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByLabelText(/I am 18 or older, and I accept/));
  await user.click(screen.getByRole("button", { name: "Create account" }));
  await screen.findByRole("heading", { name: "Check your inbox" });
  document.body.innerHTML = "";
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

  it("AC-4: sign-up does not sign in; it asks the user to check their inbox", async () => {
    const bodies = recordBodies("/api/auth/password/signup");
    const user = renderAt("/signin");
    await user.click(await screen.findByRole("tab", { name: "Create account" }));
    await user.type(screen.getByLabelText("Email address"), "ana@example.com");
    await user.type(screen.getByLabelText("Your name (optional)"), "Ana Lopez");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByLabelText(/I am 18 or older, and I accept/));
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: "Check your inbox" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("We sent a link to ana@example.com.");
    expect(screen.getByRole("button", { name: "Resend the link" })).toBeInTheDocument();
    expect(await (await fetch(`${API_BASE}/auth/me`)).json()).toMatchObject({ status: "signed_out" });
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

  it("AC-4: the resend and different-email buttons on the check-your-inbox screen", async () => {
    const bodies = recordBodies("/api/auth/password/resend");
    const user = renderAt("/signin?mode=signup");
    await user.type(await screen.findByLabelText("Email address"), "flo@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByLabelText(/I am 18 or older, and I accept/));
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await user.click(await screen.findByRole("button", { name: "Resend the link" }));
    expect(await screen.findByText(/We sent a new link/)).toBeInTheDocument();
    expect(bodies).toEqual([{ email: "flo@example.com" }]);

    await user.click(screen.getByRole("button", { name: "Use a different email" }));
    expect(screen.getByRole("tab", { name: "Create account", selected: true })).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toHaveValue("");
  });

  it("AC-4: password sign-in is refused until the email is confirmed, with a way to resend", async () => {
    await signUp("gus@example.com", "correct horse battery");
    const bodies = recordBodies("/api/auth/password/resend");
    const user = renderAt("/signin");
    await user.type(await screen.findByLabelText("Email address"), "gus@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Check your inbox" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Confirm your email before you sign in.");
    await user.click(screen.getByRole("button", { name: "Resend the link" }));
    await screen.findByText(/We sent a new link/);
    expect(bodies).toEqual([{ email: "gus@example.com" }]);
  });

  it("AC-4: the confirmation link signs in and opens the profile step on /welcome", async () => {
    await signUp("hal@example.com", "correct horse battery");
    await confirmEmail("hal@example.com");
    renderAt("/welcome");
    expect(await screen.findByRole("heading", { name: "Tell us about yourself" })).toBeInTheDocument();
  });

  it("AC-4: a wrong password is refused, the right one signs in", async () => {
    await signUp("dee@example.com", "correct horse battery");
    await confirmEmail("dee@example.com");
    await fetch(`${API_BASE}/auth/logout`, { method: "POST" });

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
    await signUp("eve@example.com", "first password");

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
    await signUp("cy@example.com", "first long secret");

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
