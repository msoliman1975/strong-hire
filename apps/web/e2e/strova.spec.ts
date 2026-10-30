import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/**
 * U13: the five flows of the Strova mockups (docs/ux-strova/reference/mockups.html), end to end
 * with every API call mocked and `v2_enabled` on. The v1 journey stays in journey.spec.ts.
 */

const SHOTS = process.env.E2E_SCREENSHOTS;
const KEY = "strong-hire-mock-db-v5";

/**
 * Each screen of the flows: a screenshot when E2E_SCREENSHOTS is set, and an axe check against
 * WCAG 2.1 A and AA (names, labels, contrast, structure). Any violation fails the test.
 */
async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/strova-${name}.png`, fullPage: true });
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const found = violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect.soft(found, `accessibility of ${name}`).toEqual([]);
}

test.describe.configure({ timeout: 90_000 });

/** Turns `v2_enabled` on in the mocked GET /status before the app loads. */
test.beforeEach(async ({ page }) => {
  await page.addInitScript((key) => {
    if (!localStorage.getItem(key))
      localStorage.setItem(
        key,
        JSON.stringify({
          siteStatus: {
            banner: null,
            signups_open: true,
            voice_sessions_open: true,
            text_sessions_open: true,
            custom_interview_access: "everyone",
            v2_enabled: true,
          },
        }),
      );
  }, KEY);
  // The first-run tour can open on any app page; skip it the way a user would.
  await page.addLocatorHandler(page.getByRole("button", { name: "Skip the tour" }), async (skip) => {
    await skip.click();
  });
});

async function signUp(page: Page, email: string) {
  await page.goto("/");
  await expect(page).toHaveURL(/\/signin$/);
  await page.getByLabel("Email for dev login").fill(email);
  await page.getByRole("button", { name: "Sign in as dev user" }).click();
  await page.getByLabel("I am 18 or older.").check();
  await page.getByLabel("I accept the terms of service and the privacy policy.").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Tell us about yourself" })).toBeVisible();
  await page.getByLabel("Full name").fill("Ana Lopez");
  await page.getByLabel("Years of experience").fill("7");
  await page.getByLabel("Level you are interviewing for").selectOption("senior");
  await page.getByRole("button", { name: "Save and continue" }).click();
}

const RESUME = [
  "Ana Lopez",
  "Backend engineer with 7 years in billing and payments systems.",
  "",
  "Software Engineer II, Shoply, Mar 2021 to now",
  "- Built the refunds API used by 40,000 merchants",
  "- Led migration of 30 services to PostgreSQL 15 with zero downtime",
  "",
  "Software Engineer, Invoicely, Jun 2018 to Feb 2021",
  "- Cut nightly invoice job runtime from 4 hours to 25 minutes",
  "",
  "Skills: Python, Go, PostgreSQL, Kafka, AWS",
].join("\n");

/** First use: profile, resume, reading, results, breakdown and issues, plan style, what first. */
async function firstUse(page: Page, email: string, style: "weekly plan" | "checklist" = "weekly plan") {
  await signUp(page, email);
  await expect(page.getByRole("heading", { name: "Start with your resume" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Setup steps" })).toBeVisible();
  await shot(page, "01-start");
  await page.getByLabel("Or paste your resume text").fill(RESUME);
  await page.getByRole("button", { name: "Read my resume" }).click();
  await expect(page.getByRole("heading", { name: "Strova is reading your resume" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Strova is analysing" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Here is what your resume shows" })).toBeVisible({ timeout: 15_000 });
  await shot(page, "02-results");
  // The three results are folds: open the issues and follow it to the full breakdown.
  await page.getByText("Resume issues", { exact: true }).click();
  await page.getByRole("link", { name: "Open breakdown and issues" }).last().click();
  await expect(page.getByRole("heading", { name: "Breakdown and issues", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Breakdown", level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Issues", level: 2 })).toBeVisible();
  await shot(page, "03-breakdown");
  await page.getByRole("link", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "How do you like to work?" })).toBeVisible();
  if (style === "checklist") await page.getByRole("button", { name: /Work through a list/ }).click();
  await shot(page, "04-plan-style");
  await page.getByRole("button", { name: `Use the ${style}` }).click();
  await expect(page.getByRole("heading", { name: "What would you like to do first?" })).toBeVisible();
  await shot(page, "05-what-first");
}

test("first use: profile, resume, results, breakdown, plan style, what first, Home", async ({ page }) => {
  await firstUse(page, "first@example.com");
  await page.getByRole("link", { name: "go to Home" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening), Ana$/ })).toBeVisible();
  const hero = page.getByRole("region", { name: "Strova's next step" });
  await expect(hero.getByRole("img", { name: "Strova is coaching" })).toBeVisible();
  await expect(page.getByTestId("weekly-plan")).toBeVisible();
  await shot(page, "06-home");
});

const POSTING =
  "Stripe is hiring a Senior Software Engineer, Payments Reliability. Must have: Python or Go, distributed systems, on-call ownership, payments. ".repeat(3);

/** Add a target role: posting, check the details, choose interviews, then the role page. */
async function addRole(page: Page) {
  await page.getByRole("link", { name: /I'm applying to a role/ }).click();
  await expect(page.getByRole("heading", { name: "Add a target role", level: 1 })).toBeVisible();
  await expect(page.getByRole("list", { name: "Add a target role steps" })).toBeVisible();
  await page.getByRole("button", { name: "paste the text" }).click();
  await page.getByLabel("Job posting text").fill(POSTING);
  await shot(page, "10-add-role");
  await page.getByRole("button", { name: "Read the posting" }).click();
  await expect(page.getByLabel("Company")).toBeVisible({ timeout: 15_000 });
  await shot(page, "11-add-role-check");
  await page.getByRole("button", { name: "Looks right" }).click();
  await expect(page.getByRole("heading", { name: /^Interviews Strova suggests for / })).toBeVisible();
  await shot(page, "12-add-role-interviews");
  await page.getByRole("button", { name: "Create the role" }).click();
  await expect(page).toHaveURL(/\/roles\/[^/]+$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Interviews for this role" })).toBeVisible();
}

test("add a target role: three steps, then the role page", async ({ page }) => {
  await firstUse(page, "role@example.com");
  await addRole(page);
  await expect(page.getByRole("heading", { name: "What they'll look for" })).toBeVisible();
  await shot(page, "13-role");
});

test("rehearse: interview page, take, live room, debrief, apply a suggestion, undo", async ({ page }) => {
  await firstUse(page, "rehearse@example.com");
  await addRole(page);
  await page.getByRole("link", { name: /^Behavioral .*Start a take$/ }).click();
  const next = page.getByRole("region", { name: "Next take" });
  await expect(next).toBeVisible();
  await shot(page, "20-interview");
  await next.getByRole("button", { name: /Start/ }).click();
  await expect(page).toHaveURL(/live/, { timeout: 15_000 });
  await page.getByRole("button", { name: "Check my microphone" }).click();
  await page.getByRole("button", { name: "Join the interview" }).click({ timeout: 15_000 });
  await expect(page.getByRole("img", { name: "Strova is interviewing" })).toBeVisible({ timeout: 15_000 });
  await shot(page, "21-live");
  await page.getByRole("button", { name: "End take" }).first().click();
  await page.locator("dialog[open]").getByRole("button", { name: "End take" }).click();
  await expect(page).toHaveURL(/debrief/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Strova's verdict" })).toBeVisible({ timeout: 60_000 });
  await shot(page, "22-debrief");
  await page.getByRole("button", { name: "Apply", exact: true }).first().click();
  const undo = page.getByRole("button", { name: "Undo" }).first();
  await expect(undo).toBeVisible();
  await shot(page, "23-applied");
  await undo.click();
  await expect(page.getByRole("button", { name: "Apply", exact: true }).first()).toBeVisible();
});

test("build a story: craft with Strova; write it yourself, review, accept an edit", async ({ page }) => {
  await firstUse(page, "stories@example.com");
  await page.getByRole("link", { name: "go to Home" }).click();
  await page.getByRole("navigation").getByRole("link", { name: "Career Stories with Strova" }).click();
  await expect(page.getByRole("heading", { name: "Career Stories with Strova", level: 1 })).toBeVisible();
  await shot(page, "30-stories");

  // Craft with Strova: answer in your own words, then save and open the story.
  await page.getByRole("link", { name: /Craft with Strova/ }).first().click();
  const typeInstead = page.getByRole("button", { name: "Type instead" });
  const reply = page.getByLabel("Your reply");
  await expect(typeInstead.or(reply)).toBeVisible({ timeout: 15_000 });
  if (await typeInstead.isVisible()) await typeInstead.click();
  await reply.fill("At Shoply I led the move of 30 services to PostgreSQL 15 with zero downtime.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("log", { name: "Conversation with your coach" })).toContainText("30 services");
  await expect(page.getByRole("complementary", { name: "Story taking shape" })).toBeVisible();
  await shot(page, "31-craft");
  await page.getByRole("button", { name: "Save and exit" }).click();
  await expect(page).toHaveURL(/\/stories\/[^/]+$/, { timeout: 15_000 });
  await expect(page.getByRole("list", { name: "Status steps" })).toBeVisible();
  await shot(page, "32-story");

  // Write it yourself, then ask Strova to review and accept one edit.
  await page.goto("/stories/new");
  await page.getByLabel("Story title").fill("Pushback from platform");
  await page.getByLabel(/Context/).fill("The platform team refused to change an API my team needed for the new checkout.");
  await page.getByLabel(/Stakes/).fill("Without it, we would miss the holiday launch.");
  await page.getByLabel(/Your action/).fill("We talked to them and worked it out.");
  await shot(page, "33-write");
  await page.getByRole("button", { name: "Save as a Draft" }).click();
  await page.getByRole("link", { name: /Pushback from platform/ }).first().click();
  await page.getByRole("link", { name: "Review with Strova" }).click();
  await page.getByRole("button", { name: "Review with Strova" }).click();
  const review = page.getByRole("region", { name: "Strova's review" });
  await expect(review.getByRole("heading", { name: "Strova's review" })).toBeVisible({ timeout: 15_000 });
  await shot(page, "34-review");
  const edit = review.getByRole("group", { name: /^Edit to / }).first();
  const part = ((await edit.getAttribute("aria-label")) ?? "").replace("Edit to ", "");
  await edit.getByRole("button", { name: "Accept" }).click();
  await expect(review.getByRole("status").filter({ hasText: `${part} updated.` })).toBeVisible();
  await shot(page, "35-review-accepted");
});

test("returning: Home plan items open the interview, the story work and the resume", async ({ page }) => {
  await firstUse(page, "returning@example.com", "checklist");
  await addRole(page);
  const home = async () => {
    await page.getByRole("navigation").getByRole("link", { name: "Home" }).click();
    await expect(page.getByTestId("checklist-plan")).toBeVisible({ timeout: 15_000 });
  };
  const group = async (kind: string, title: string) => {
    const g = page.getByTestId(`group-${kind}`);
    await g.getByText(title, { exact: true }).click();
    return g;
  };
  await home();
  await expect(page.getByRole("region", { name: "Strova's next step" })).toContainText("Rehearse");
  await shot(page, "40-home-checklist");

  await (await group("rehearsal", "Rehearsals")).getByRole("link").first().click();
  await expect(page.getByRole("region", { name: "Next take" })).toBeVisible();

  await home();
  await (await group("story", "Story completion")).getByRole("link").first().click();
  await expect(page).toHaveURL(/\/(stories|coach)\//);
  await expect(page.getByRole("region", { name: "Story parts" }).or(page.getByRole("list", { name: "Story parts" }))).toBeVisible({
    timeout: 15_000,
  });

  await home();
  await (await group("resume", "Resume gaps and issues")).getByRole("link").first().click();
  await expect(page).toHaveURL(/\/resumes\/[^/]+$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shot(page, "41-resume");
});

test("accessibility: Home by keyboard with visible focus; Strova's animation stops under reduced motion", async ({ page }) => {
  await firstUse(page, "keys@example.com");
  await page.getByRole("link", { name: "go to Home" }).click();
  const hero = page.getByRole("region", { name: "Strova's next step" });
  const avatar = hero.getByRole("img", { name: "Strova is coaching" });
  await expect(avatar).toBeVisible();
  const running = () => avatar.evaluate((el) => el.getAnimations({ subtree: true }).length);
  expect(await running()).toBeGreaterThan(0);

  // Tab from the page heading to Strova's next step, with a visible focus ring, and open it.
  const action = hero.getByRole("link").first();
  await page.getByRole("heading", { level: 1 }).focus();
  for (let n = 0; n < 40 && !(await action.evaluate((el) => el === document.activeElement)); n++) await page.keyboard.press("Tab");
  await expect(action).toBeFocused();
  expect(await action.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe("none");
  const href = await action.getAttribute("href");
  await page.keyboard.press("Enter");
  await expect.poll(() => {
    const url = new URL(page.url());
    return url.pathname + url.search;
  }).toBe(href);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(avatar).toBeVisible();
  expect(await running()).toBe(0);
});
