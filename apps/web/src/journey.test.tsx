/**
 * The main candidate journey in jsdom, against the MSW mock API. Requirement IDs: AC-2
 * (consent off by default), IN-1 (paste fallback), IN-2 (confirm the posting), IN-3 (resume),
 * IN-4 (optional context can be skipped),
 * BL-2 (two free mini interviews, then the paywall), BL-1 (usage meter).
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { AppRoutes, createQueryClient } from "./App";
import { CONSENT_LABEL } from "./components/ConsentSwitch";
import { server } from "./mocks/node";
import { MOCK_QUESTION } from "./session/mockVoice";

// jsdom has no microphone. The live page's mic check gets a working one.
vi.mock("./session/microphone", async (original) => ({
  ...(await original<typeof import("./session/microphone")>()),
  openMicrophone: async () => ({ level: () => 0.5, stop: () => undefined }),
}));

type User = ReturnType<typeof userEvent.setup>;

function renderApp(path = "/"): User {
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

/** Collects the JSON bodies the app sends to POST /auth/signup. */
function recordSignupBodies(): unknown[] {
  const bodies: unknown[] = [];
  server.events.on("request:start", async ({ request }) => {
    if (request.url.endsWith("/api/auth/signup")) bodies.push(await request.clone().json());
  });
  return bodies;
}

async function startSignup(user: User) {
  await user.click(await screen.findByRole("button", { name: "Sign in as dev user" }));
  expect(await screen.findByRole("heading", { name: "Create your account" })).toBeInTheDocument();
}

async function signUp(user: User) {
  await startSignup(user);
  expect(screen.getByRole("checkbox", { name: CONSENT_LABEL })).not.toBeChecked();
  await user.click(screen.getByLabelText("I am 18 or older."));
  await user.click(screen.getByLabelText("I accept the terms of service and the privacy policy."));
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(await screen.findByRole("heading", { name: "Your interviews" })).toBeInTheDocument();
}

/** Setup, live session and debrief of a free mini interview. */
async function runMiniInterview(user: User) {
  expect(await screen.findByRole("heading", { name: "Set up your interview" })).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /^10 minutes \(mini\)/ })).toBeChecked();
  expect(screen.getByRole("radio", { name: /^30 minutes/ })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Start interview" }));

  expect(await screen.findByRole("heading", { name: "Interview in progress" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Check my microphone" }));
  await user.click(await screen.findByRole("button", { name: "Join the interview" }));
  expect(await screen.findByText(MOCK_QUESTION, {}, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.getByTestId("timer")).toHaveTextContent(/^(10:00|9:5\d)$/);
  await user.click(screen.getByRole("button", { name: "End interview" }));
  const dialog = screen.getByRole("dialog", { name: "End the interview?" });
  await user.click(within(dialog).getByRole("button", { name: "End interview" }));

  expect(await screen.findByTestId("hire-signal")).toHaveTextContent("Lean Hire");
  expect(screen.getByTestId("mini-note")).toHaveTextContent("Practice signal only.");
}

describe("main journey", () => {
  it("goes from sign-in to two mini debriefs, then shows the paywall", async () => {
    const signupBodies = recordSignupBodies();
    const user = renderApp();

    // Signed-out users land on sign-in.
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await signUp(user);
    expect(signupBodies).toEqual([{ age_confirmed: true, terms_accepted: true, training_consent: false }]);
    expect(await screen.findByTestId("usage-meter")).toHaveTextContent("2 free mini interviews left");

    // Job posting, confirm, resume, skip context.
    await user.click(screen.getByRole("link", { name: "Add a job" }));
    await user.type(screen.getByLabelText("Or paste the job posting text"), "Senior engineer, payments. ".repeat(5));
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    expect(await screen.findByRole("heading", { name: "Check the job details" })).toBeInTheDocument();
    expect(screen.getByLabelText("Company")).toHaveValue("Stripe");
    await user.click(screen.getByRole("button", { name: "Save and continue" }));

    expect(await screen.findByRole("heading", { name: "Add your resume" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Or paste your resume text"), "Backend engineer");
    await user.click(screen.getByRole("button", { name: "Upload resume" }));
    expect(await screen.findByRole("heading", { name: "Roles" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Check and continue" }));
    expect(await screen.findByRole("heading", { name: "Check your CV" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Confirm and continue" }));

    expect(await screen.findByRole("heading", { name: "Add context (optional)" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Skip this step" }));

    // Gap analysis.
    expect(await screen.findByTestId("match-score")).toHaveTextContent("72");
    expect(screen.getByText("No clear technical leadership across teams")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Start the recommended session" }));

    // Session setup: the level comes from the job posting. A free account gets a mini.
    expect(await screen.findByRole("heading", { name: "Set up your interview" })).toBeInTheDocument();
    expect(screen.getByLabelText("Level")).toHaveValue("senior");
    expect(screen.getByRole("radio", { name: /^Behavioral/ })).toBeChecked();
    await runMiniInterview(user);
    expect(screen.getByRole("heading", { name: "Question by question" })).toBeInTheDocument();

    // Dashboard shows the job. A mini is not in the trends.
    await user.click(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Your interviews" }));
    expect(await screen.findByText(/^1 session, last on/)).toBeInTheDocument();
    expect(await screen.findByText(/Trends appear here after your first full Realistic session/)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /^Ownership:/ })).not.toBeInTheDocument();
    expect(screen.getByTestId("usage-meter")).toHaveTextContent("1 free mini interview left");

    // The second free mini interview.
    await user.click(await screen.findByRole("link", { name: /Start next/ }));
    await runMiniInterview(user);
    await user.click(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Your interviews" }));
    expect(await screen.findByText(/^2 sessions, last on/)).toBeInTheDocument();
    expect(screen.getByTestId("usage-meter")).toHaveTextContent("free mini interviews used");

    // BL-2: the API refuses a third free interview, and the app shows the paywall.
    await user.click(await screen.findByRole("link", { name: /Start next/ }));
    await user.click(await screen.findByRole("button", { name: "Start interview" }));
    expect(await screen.findByRole("heading", { name: "Keep practicing" })).toBeInTheDocument();
    expect(screen.getByText("You have used your free mini interviews. Gap analyses stay free.")).toBeInTheDocument();
    expect(await screen.findByText("$29")).toBeInTheDocument();
  }, 45_000);

  it("AC-2: consent is sent as true only when the user turns it on", async () => {
    const signupBodies = recordSignupBodies();
    const user = renderApp("/signin");
    await startSignup(user);
    await user.click(screen.getByLabelText("I am 18 or older."));
    await user.click(screen.getByLabelText("I accept the terms of service and the privacy policy."));
    await user.click(screen.getByRole("checkbox", { name: CONSENT_LABEL }));
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await screen.findByRole("heading", { name: "Your interviews" });
    expect(signupBodies).toEqual([{ age_confirmed: true, terms_accepted: true, training_consent: true }]);
  });

  it("sign-up is blocked without the 18+ confirmation", async () => {
    const signupBodies = recordSignupBodies();
    const user = renderApp("/signin");
    await startSignup(user);
    await user.click(screen.getByLabelText("I accept the terms of service and the privacy policy."));
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText("You must be 18 or older to use Strong Hire.")).toBeInTheDocument();
    expect(screen.getByLabelText("I am 18 or older.")).toHaveAttribute("aria-invalid", "true");
    expect(signupBodies).toEqual([]);
  });

  it("signed-out users are sent to sign-in from any page", async () => {
    renderApp("/account");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("IN-1: LinkedIn cannot be read, so the user pastes the text and the link is kept", async () => {
    const jobBodies: unknown[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "POST" && request.url.endsWith("/api/job-targets")) {
        jobBodies.push(await request.clone().json());
      }
    });
    const user = renderApp("/signin");
    await signUp(user);
    await user.click(screen.getByRole("link", { name: "Add a job" }));
    const link = "https://www.linkedin.com/jobs/view/1";
    await user.type(screen.getByLabelText("Job posting link"), link);
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This site does not allow automatic reading.");

    await user.type(screen.getByLabelText("Or paste the job posting text"), "Senior engineer, payments. ".repeat(5));
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    expect(await screen.findByRole("heading", { name: "Check the job details" })).toBeInTheDocument();
    expect(jobBodies).toEqual([
      { url: link, text: null },
      { url: link, text: "Senior engineer, payments. ".repeat(5).trim() },
    ]);
  });

  it("IN-1: when the background job cannot read the page, the user pastes the text", async () => {
    const user = renderApp("/signin");
    await signUp(user);
    await user.click(screen.getByRole("link", { name: "Add a job" }));
    await user.type(screen.getByLabelText("Job posting link"), "https://jobs.blocked.example/42");
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    expect(await screen.findByRole("heading", { name: "Paste the job posting" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("This job board blocks automatic reading.");

    await user.type(screen.getByLabelText("Job posting text"), "Senior engineer, payments. ".repeat(5));
    await user.click(screen.getByRole("button", { name: "Read job posting" }));
    expect(await screen.findByRole("heading", { name: "Check the job details" })).toBeInTheDocument();
  });
});
