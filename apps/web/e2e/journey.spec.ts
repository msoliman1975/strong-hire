import { expect, test, type Page } from "@playwright/test";

/**
 * Smoke test of the main journey with every API call mocked:
 * sign in, sign up, job posting, resume, context, gap analysis, session setup, live session,
 * debrief, dashboard trend, paywall after the free interview (BL-2), subscribe, account.
 */

const SHOTS = process.env.E2E_SCREENSHOTS;

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

async function signUp(page: Page, email: string, consent = false) {
  await page.goto("/");
  await expect(page).toHaveURL(/\/signin$/);
  await shot(page, "01-signin");
  await page.getByLabel("Email for dev login").fill(email);
  await page.getByRole("button", { name: "Sign in as dev user" }).click();
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await expect(page.getByRole("switch", { name: "Use my transcripts to improve Strong Hire" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  await shot(page, "02-signup");
  await page.getByLabel("I am 18 or older.").check();
  await page.getByLabel("I accept the terms of service and the privacy policy.").check();
  if (consent) await page.getByRole("switch", { name: "Use my transcripts to improve Strong Hire" }).click();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your interviews" })).toBeVisible();
}

async function addJob(page: Page) {
  await page.getByRole("link", { name: "Add a job" }).first().click();
  await expect(page.getByRole("heading", { name: "Add a job posting" })).toBeVisible();
  await page.getByLabel("Job posting link").fill("https://example-board.test/jobs/1234");
  await shot(page, "03-job");
  await page.getByRole("button", { name: "Read job posting" }).click();

  await expect(page.getByRole("heading", { name: "Check the job details" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByLabel("Company")).toHaveValue("Stripe");
  await shot(page, "04-confirm");
  await page.getByRole("button", { name: "Save and continue" }).click();

  await expect(page.getByRole("heading", { name: "Add your resume" })).toBeVisible();
  await page.getByLabel("Or paste your resume text").fill("Backend engineer, 7 years of Python and payments.");
  await page.getByRole("button", { name: "Upload resume" }).click();
  await expect(page.getByRole("heading", { name: "Roles" })).toBeVisible({ timeout: 10_000 });
  await shot(page, "05-resume");
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Add context (optional)" })).toBeVisible();
  await page.getByLabel("Interview stage").selectOption("Onsite or final loop");
  await page.getByLabel("What worries you about this interview?").fill("Leading design reviews.");
  await shot(page, "06-context");
  await page.getByRole("button", { name: "Save and see my gap analysis" }).click();

  await expect(page.getByTestId("match-score")).toContainText("72", { timeout: 10_000 });
  await shot(page, "07-gap");
}

async function runSession(page: Page) {
  await expect(page.getByRole("heading", { name: "Set up your interview" })).toBeVisible();
  await expect(page.getByLabel("Level")).toHaveValue("senior");
  await shot(page, "08-setup");
  await page.getByRole("button", { name: "Start interview" }).click();

  await expect(page.getByRole("heading", { name: "Interview in progress" })).toBeVisible();
  await shot(page, "09-live");
  await page.getByRole("button", { name: "End interview" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "End interview" }).click();

  await expect(page.getByTestId("hire-signal")).toBeVisible({ timeout: 15_000 });
  await shot(page, "10-debrief");
}

test("main journey from sign-up to paywall", async ({ page }) => {
  await signUp(page, "ana@example.com");
  await expect(page.getByTestId("usage-meter")).toContainText("1 free interview left");
  await shot(page, "02b-dashboard-empty");
  await addJob(page);

  await page.getByRole("link", { name: "Start the recommended session" }).click();
  await runSession(page);
  await expect(page.getByTestId("hire-signal")).toHaveText("Lean Hire");
  await expect(page.getByRole("heading", { name: "Question by question" })).toBeVisible();

  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByText(/^1 session, last on/)).toBeVisible();
  await expect(page.getByRole("img", { name: /^Ownership:/ })).toBeVisible();
  await expect(page.getByTestId("usage-meter")).toContainText("free interview used");
  await shot(page, "11-dashboard");

  // BL-2: the second interview needs a plan.
  await page.getByRole("link", { name: /Start next/ }).click();
  await page.getByRole("button", { name: "Start interview" }).click();
  await expect(page.getByRole("heading", { name: "Keep practicing" })).toBeVisible();
  await expect(page.getByText("You have used your free interview.")).toBeVisible();
  await shot(page, "12-paywall");
  await page.getByRole("button", { name: "Subscribe" }).click();

  await expect(page.getByText("Your plan is active.")).toBeVisible();
  await expect(page.getByTestId("usage-meter")).toContainText("0 of 300 minutes used");
});

test("account page: consent, export and delete", async ({ page }) => {
  await signUp(page, "bo@example.com");
  await page.getByRole("link", { name: "Account" }).click();
  const consent = page.getByRole("switch", { name: "Use my transcripts to improve Strong Hire" });
  await expect(consent).toHaveAttribute("aria-checked", "false");
  await consent.click();
  await expect(consent).toHaveAttribute("aria-checked", "true");
  await expect(page.getByText("Saved. Training-data use is on.")).toBeVisible();

  await page.getByRole("button", { name: "Prepare export" }).click();
  await expect(page.getByRole("link", { name: "Download export" })).toBeVisible({ timeout: 10_000 });
  await shot(page, "13-account");

  const remove = page.getByRole("button", { name: "Delete my account" });
  await expect(remove).toBeDisabled();
  await page.getByLabel("Type DELETE to confirm").fill("DELETE");
  await remove.click();
  await expect(page).toHaveURL(/\/signin\?deleted=1$/);
  await expect(page.getByText("Your account deletion has started.")).toBeVisible();
});

test("sign-up form needs the 18+ confirmation", async ({ page }) => {
  await page.goto("/signin");
  await page.getByRole("button", { name: "Sign in as dev user" }).click();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("You must be 18 or older to use Strong Hire.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
});

test("the main pages can be used with the keyboard only", async ({ page }) => {
  await page.goto("/signin");
  // The page moves focus to its heading, so the next Tab reaches the first field.
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Email address")).toBeFocused();
  await page.getByLabel("Email for dev login").focus();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Sign in as dev user" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeFocused();
});
