/**
 * Round 3 (canvas board R3 Interviews, R3 Account), with `v2_enabled` on and v1 kept with it off:
 * the add flow's step bar and word counter, the resume limits, and Account in two columns.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { ApiError } from "./api/client";
import { resumesApi } from "./api/inputs";
import { AppRoutes, createQueryClient } from "./App";
import {
  countWords,
  friendlyLimitError,
  JD_TOO_LONG,
  RESUME_TOO_BIG,
  RESUMES_FULL,
} from "./limits";
import { mockStore } from "./mocks/node";
import { validateResumeInput } from "./pages/onboarding/ResumePage";
import { setFeatureOverrides } from "./theme/features";

afterEach(() => setFeatureOverrides({}));

function signedIn(email = "ana@example.com") {
  mockStore.db.users[email] = {
    id: "00000000-0000-4000-8000-0000000000a1",
    org_id: "00000000-0000-4000-8000-0000000000b1",
    email,
    auth_provider: "password",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
}

function renderApp(path: string, v2 = true) {
  signedIn();
  setFeatureOverrides({ v2_enabled: v2 });
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

async function addResumes(n: number) {
  signedIn();
  for (let i = 0; i < n; i++) {
    const form = new FormData();
    form.append("text", `CV number ${i}. Backend engineer with Python and Go.`);
    await resumesApi.upload(form);
  }
}

const words = (n: number) => Array.from({ length: n }, (_, i) => `w${i}`).join(" ");

describe("add flow (v2)", () => {
  it("PP-1: the step bar reads Job description, Your resume, Your plan", async () => {
    renderApp("/jobs/new");
    const steps = await screen.findByText("Job description");
    expect(steps).toBeInTheDocument();
    expect(screen.getByText("Your resume")).toBeInTheDocument();
    expect(screen.getByText("Your plan")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next: pick your resume" })).toBeInTheDocument();
  });

  it("IN-1: a live word counter turns amber at 2,000 words and blocks Next past 2,500", async () => {
    renderApp("/jobs/new");
    const box = await screen.findByRole("textbox", { name: "Or paste the job posting text" });
    const user = userEvent.setup();
    await user.click(box);
    await user.paste(words(812));
    expect(screen.getByText(/812 \/ 2,500 words/)).not.toHaveAttribute("data-level");
    await user.paste(" " + words(1300));
    expect(screen.getByText(/2,112 \/ 2,500 words/)).toHaveAttribute("data-level", "warn");
    await user.paste(" " + words(500));
    const count = screen.getByText(/2,612 \/ 2,500 words/);
    expect(count).toHaveAttribute("data-level", "over");
    expect(count).toHaveTextContent("Trim the benefits and company boilerplate");
    expect(screen.getByRole("button", { name: "Next: pick your resume" })).toBeDisabled();
  });

  it("FL-1: with v2 off the add form has no word counter and the v1 steps", async () => {
    renderApp("/jobs/new", false);
    expect(await screen.findByText("Job posting")).toBeInTheDocument();
    expect(screen.queryByText(/\/ 2,500 words/)).toBeNull();
    expect(screen.getByRole("button", { name: "Read job posting" })).toBeInTheDocument();
  });

  it("IN-1: words are counted by whitespace", () => {
    expect(countWords("")).toBe(0);
    expect(countWords("  one two\nthree  ")).toBe(3);
  });
});

describe("resume limits (v2)", () => {
  it("LB-1: the Resumes page says N of 5 and up to 1 MB each", async () => {
    await addResumes(2);
    renderApp("/resumes");
    expect(await screen.findByTestId("resume-limit")).toHaveTextContent("2 of 5 · up to 1 MB each");
  });

  it("LB-1: at 5 resumes the card says Replace one and the upload is blocked", async () => {
    await addResumes(5);
    renderApp("/");
    const card = await screen.findByRole("region", { name: "The CV your interviews are measured against." });
    expect(await within(card).findByRole("link", { name: "Replace one" })).toHaveAttribute("href", "/resumes");
    expect(card).toHaveTextContent("5 of 5 · up to 1 MB each");
  });

  it("LB-1: the upload form says when the library is full", async () => {
    await addResumes(5);
    renderApp("/resumes");
    expect(await screen.findByTestId("resumes-full")).toHaveTextContent(RESUMES_FULL);
    expect(screen.getByRole("button", { name: "Upload resume" })).toBeDisabled();
  });

  it("LB-1: a file over 1 MB is refused in the browser, before any upload", () => {
    const big = new File([new Uint8Array(1024 * 1024 + 1)], "cv.pdf", { type: "application/pdf" });
    expect(validateResumeInput(big, "", 1024 * 1024)).toBe(RESUME_TOO_BIG);
    // v1 keeps its 5 MB check.
    expect(validateResumeInput(big, "")).toBeNull();
  });

  it("LB-1: the API's 413 and 422 limit refusals read in plain words", () => {
    expect((friendlyLimitError(new ApiError(413, "Payload too large")) as Error).message).toBe(RESUME_TOO_BIG);
    expect((friendlyLimitError(new ApiError(422, "The job description is over 2500 words.")) as Error).message).toBe(JD_TOO_LONG);
    expect((friendlyLimitError(new ApiError(422, "Resume limit reached", "resume_limit")) as Error).message).toBe(RESUMES_FULL);
    const other = new ApiError(422, "Something else");
    expect(friendlyLimitError(other)).toBe(other);
  });
});

describe("Account (v2)", () => {
  it("AC-3: Account shows Profile, Plan and usage, Sign-in, Privacy, Your data and Delete, in two columns", async () => {
    await addResumes(1);
    renderApp("/account");
    await screen.findByRole("heading", { level: 2, name: "Plan and usage" });
    const headings = screen.getAllByRole("heading", { level: 2 });
    const names = headings.map((h) => h.textContent);
    expect(names).toEqual(expect.arrayContaining(["Profile", "Plan and usage", "Sign-in", "Privacy", "Your data"]));
    expect(screen.getByRole("heading", { level: 1, name: "Account" }).closest(".account-v2")).not.toBeNull();
    expect(await screen.findByTestId("account-resumes")).toHaveTextContent("Resumes: 1 of 5");
    expect(screen.getByText("Email and password")).toBeInTheDocument();
    // My questions moved into the Question bank.
    expect(screen.queryByRole("heading", { name: "My questions" })).toBeNull();
  });

  it("FL-1: with v2 off, Account keeps its one column and v1 sections", async () => {
    renderApp("/account", false);
    expect(await screen.findByRole("heading", { level: 2, name: "My questions" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign-in" })).toBeNull();
  });
});
