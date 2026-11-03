import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/**
 * RMAP-9 (RSD-15; verifies RSD-1 to RSD-16): the resume screens redesign end to end on the mock
 * app with `v2_enabled` on. One journey across the Resumes list, the guided check page and Target
 * roles, then axe and no horizontal scroll on every screen, step and drawer at 1280 and 390.
 */

const KEY = "strong-hire-mock-db-v5";
const SHOTS = process.env.E2E_SCREENSHOTS;

test.describe.configure({ timeout: 120_000 });

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
  await page.addLocatorHandler(page.getByRole("button", { name: "Skip the tour" }), async (skip) => {
    await skip.click();
  });
});

const RESUME = [
  "Ana Lopez",
  "Backend engineer with 7 years in billing and payments systems.",
  "",
  "Software Engineer II, Shoply, Mar 2021 to now",
  "- Built the refunds API used by 40,000 merchants",
  "",
  "Software Engineer, Invoicely, Jun 2018 to Feb 2021",
  "- Cut nightly invoice job runtime from 4 hours to 25 minutes",
  "",
  "Skills: Python, Go, PostgreSQL, Kafka, AWS",
].join("\n");

const POSTING =
  "Stripe is hiring a Senior Software Engineer, Payments Reliability. Must have: Python or Go, distributed systems, on-call ownership, payments. ".repeat(3);

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
  await expect(page.getByRole("heading", { name: "Start with your resume" })).toBeVisible();
}

/**
 * The mock store, through the app's own API (the service worker answers). Two resumes and a role.
 * The default resume has a high-severity finding (Studio Nine ends before it starts), a 9-month
 * gap before Shoply and a missing start date (Freelance), so every finding kind shows.
 */
interface SeedRole {
  company: string;
  title: string;
  start: string | null;
  end: string | null;
  achievements: string[];
  skills: string[];
}
interface SeedResume {
  id: string;
  resume: { roles: SeedRole[] } | null;
}

async function seed(page: Page) {
  return page.evaluate(
    async ([text, posting]) => {
      const json = { "content-type": "application/json" };
      const upload = async (t: string): Promise<SeedResume & { resume: NonNullable<SeedResume["resume"]> }> => {
        const form = new FormData();
        form.append("text", t);
        const { resume } = (await (await fetch("/api/resumes", { method: "POST", body: form })).json()) as { resume: { id: string } };
        let record: SeedResume = { id: resume.id, resume: null };
        for (let i = 0; i < 40; i += 1) {
          record = (await (await fetch(`/api/resumes/${resume.id}`)).json()) as SeedResume;
          if (record.resume) break;
          await new Promise((ok) => setTimeout(ok, 250));
        }
        if (!record.resume) throw new Error("The mock did not read the resume.");
        return record as SeedResume & { resume: NonNullable<SeedResume["resume"]> };
      };
      const main = await upload(text);
      const r = main.resume;
      r.roles[1].end = "2020-06";
      r.roles.push(
        { company: "Studio Nine", title: "Junior Developer", start: "2017-06", end: "2016-01", achievements: ["Built the booking widget"], skills: [] },
        { company: "Freelance", title: "Developer", start: null, end: "2015-06", achievements: ["Shipped five client sites"], skills: [] },
      );
      await fetch(`/api/resumes/${main.id}`, { method: "PUT", headers: json, body: JSON.stringify({ resume: r }) });
      await fetch(`/api/resumes/${main.id}`, { method: "PATCH", headers: json, body: JSON.stringify({ name: "Senior SWE resume" }) });
      const other = await upload(text.replace("Ana Lopez", "Ana Lopez (platform)"));
      const created = (await (await fetch("/api/job-targets", { method: "POST", headers: json, body: JSON.stringify({ text: posting }) })).json()) as {
        job_target: { id: string };
      };
      const jobId = created.job_target.id;
      for (let i = 0; i < 20; i += 1) {
        const j = (await (await fetch(`/api/job-targets/${jobId}`)).json()) as { posting?: { title?: string | null } | null };
        if (j.posting?.title) break;
        await new Promise((ok) => setTimeout(ok, 250));
      }
      await fetch(`/api/roles/${jobId}/interviews`, {
        method: "POST",
        headers: json,
        body: JSON.stringify({ interview_types: ["behavioral"], resume_id: main.id }),
      });
      return { mainId: main.id as string, otherId: other.id as string, jobId: jobId as string };
    },
    [RESUME, POSTING] as const,
  );
}

/** Opens a page; the first visit may stop on the plan style step, which a new user picks once. */
async function visit(page: Page, path: string) {
  await page.goto(path);
  const style = page.getByRole("button", { name: "Use the weekly plan" });
  if (await style.isVisible({ timeout: 3000 }).catch(() => false)) {
    await style.click();
    await page.waitForTimeout(500);
    await page.goto(path);
  }
}

/** RSD-15: no WCAG 2.1 A or AA violation and no horizontal scroll. */
async function check(page: Page, name: string) {
  // Let the drawer's slide-in finish: mid-fade text would read as low contrast.
  await page.evaluate("Promise.all(document.getAnimations().map((a) => a.finished.catch(() => undefined)))");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/rs-${name}.png`, fullPage: true });
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const found = violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect.soft(found, `accessibility of ${name}`).toEqual([]);
  const scroll = Number(await page.evaluate("document.documentElement.scrollWidth - window.innerWidth"));
  expect.soft(scroll, `horizontal scroll on ${name}`).toBeLessThanOrEqual(0);
}

const steps = (page: Page) => page.getByRole("navigation", { name: "Steps" });
const step = (page: Page, name: RegExp) => steps(page).getByRole("button", { name });
const count = async (page: Page, name: RegExp) => Number(await step(page, name).locator(".cvc-step__num").textContent());
const finding = (page: Page) => page.getByTestId("findings-step").getByRole("article");

test("RSD-1 to RSD-14: Resumes, the guided check page and Target roles work together", async ({ page }) => {
  await signUp(page, "resume-screens@example.com");
  const { mainId, otherId, jobId } = await seed(page);

  // 1. Resumes: three tiles, and the ▲ on the default resume (RSD-1, RSD-2).
  await visit(page, "/resumes");
  const list = page.getByRole("list", { name: "Your resumes" });
  const main = list.getByRole("region", { name: "Senior SWE resume" });
  await expect(main.getByText("Default", { exact: true })).toBeVisible();
  await expect(main.getByRole("term")).toHaveText(["role", /^open issues?$/, /^story ideas?$/]);
  await expect(main.getByRole("img", { name: "Includes high-severity issues" })).toBeVisible();

  // 2. Rename the other resume, then make it the default (RSD-3).
  const other = list.getByRole("listitem").filter({ hasNot: page.getByText("Senior SWE resume") });
  await other.getByRole("button", { name: /^Rename / }).click();
  await other.getByLabel("New name").fill("Platform resume");
  await other.getByRole("button", { name: "Save name" }).click();
  const platform = list.getByRole("region", { name: "Platform resume" });
  await platform.getByRole("button", { name: "Set Platform resume as default" }).click();
  await expect(platform.getByText("Default", { exact: true })).toBeVisible();
  await expect(main.getByText("Default", { exact: true })).toHaveCount(0);

  // 3. Show details lands on the check page, on Strova's findings (RSD-8).
  await main.getByRole("link", { name: /^Show details/ }).click();
  await expect(page).toHaveURL(new RegExp(`/resumes/${mainId}/check$`));
  await expect(step(page, /Strova's findings/)).toHaveAttribute("aria-current", "step");
  await expect(finding(page).getByTestId("finding-position")).toHaveText(/^Finding 1 of \d+ · high$/);

  // 4. Fix the gap in place: the count drops and the next finding shows (RSD-10).
  const before = await count(page, /Strova's findings/);
  await page.getByRole("list", { name: "Next findings" }).getByRole("button", { name: /gap.*between Invoicely and Shoply/ }).click();
  await finding(page).getByLabel("Invoicely ended").fill("2021-01");
  await finding(page).getByRole("button", { name: "Save dates" }).click();
  await expect.poll(() => count(page, /Strova's findings/)).toBe(before - 1);
  await expect(page.getByTestId("findings-step").getByText(/between Invoicely and Shoply/)).toHaveCount(0);

  // 5. Accept a finding with a reason, then Undo it from the drawer (IN-12, RSD-14).
  await page.getByRole("list", { name: "Next findings" }).getByRole("button", { name: /No start date on Freelance/ }).click();
  await finding(page).getByRole("button", { name: "Accept: Left out on purpose (age bias)" }).click();
  await page.getByRole("button", { name: "Findings you accepted · 1 ›" }).click();
  const accepted = page.getByRole("dialog", { name: "Findings you accepted · 1" });
  await expect(accepted.getByText(/Left out on purpose \(age bias\)/)).toBeVisible();
  await accepted.getByRole("button", { name: "Undo accepting No start date on Freelance" }).click();
  await page.keyboard.press("Escape");
  await expect(accepted).toBeHidden();

  // 6. Open the journey from the strip, edit an achievement, save (RSD-9, RSD-13).
  await page.getByRole("region", { name: "Career journey at a glance" }).getByRole("button", { name: "Open and edit" }).click();
  await expect(step(page, /Your career journey/)).toHaveAttribute("aria-current", "step");
  await page.getByRole("button", { name: "Edit Software Engineer II · Shoply" }).click();
  const editor = page.getByRole("group", { name: "Editing · Software Engineer II · Shoply" });
  await editor.getByRole("textbox", { name: "Achievement 1 at Software Engineer II · Shoply", exact: true }).fill("Built the refunds API used by 40,000 merchants in 12 countries");
  await editor.getByRole("button", { name: "Save role" }).click();
  // Save changes keeps the page; a reload shows the saved line.
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Changes saved.").first()).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/resumes/${mainId}/check`));
  await visit(page, `/resumes/${mainId}/check?step=journey`);
  await expect(page.getByText("Built the refunds API used by 40,000 merchants in 12 countries")).toBeVisible();

  // 7. Stories: Not a story, then Craft with Strova reaches the coach start (RSD-11).
  await step(page, /Stories to tell/).click();
  const ideas = await count(page, /Stories to tell/);
  const idea = page.getByTestId("stories-step").getByRole("article");
  await idea.getByRole("button", { name: "Not a story" }).click();
  await expect.poll(() => count(page, /Stories to tell/)).toBe(ideas - 1);
  await idea.getByRole("link", { name: "Craft with Strova" }).click();
  await expect(page).toHaveURL(/\/coach\/new\?resume=/);
  await page.goBack();

  // 8. Lines: Add to resume, then Undo (RSD-12).
  await step(page, /Stronger resume lines/).click();
  const line = page.getByRole("region", { name: "Strova suggests a resume line" });
  await line.getByRole("button", { name: "Add to resume" }).click();
  await expect(line.getByText("Added to your resume.")).toBeVisible();
  await line.getByRole("button", { name: "Undo" }).click();
  await expect(line.getByRole("button", { name: "Add to resume" })).toBeVisible();

  // 9. The roles drawer: go to the role, and come back with the browser (RSD-7, RSD-14).
  await page.getByTestId("used-by").click();
  const roles = page.getByRole("dialog", { name: "Used by 1 role" });
  await roles.getByRole("link", { name: /^Open / }).click();
  await expect(page).toHaveURL(new RegExp(`/roles/${jobId}$`));
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/resumes/${mainId}/check`));

  // 10. An old /resumes/{id} link lands on the check page (RSD-6).
  await visit(page, `/resumes/${otherId}?step=stories`);
  await expect(page).toHaveURL(new RegExp(`/resumes/${otherId}/check\\?step=stories$`));

  // 11. Target roles: tiles and Show details (RSD-4).
  await visit(page, "/roles");
  const card = page.getByRole("region").filter({ has: page.getByRole("link", { name: /^Show details/ }) }).first();
  await expect(card.getByRole("term")).toHaveText(["match", /^interviews?$/, /^days? left$/]);
  await card.getByRole("link", { name: /^Show details/ }).click();
  await expect(page).toHaveURL(new RegExp(`/roles/${jobId}$`));
});

for (const [width, height] of [
  [1280, 900],
  [390, 844],
] as const) {
  test(`RSD-15: Resumes, Target roles, every check step and drawer pass axe with no horizontal scroll at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await signUp(page, `axe-${width}@example.com`);
    const { mainId } = await seed(page);

    await visit(page, "/resumes");
    await expect(page.getByRole("list", { name: "Your resumes" })).toBeVisible();
    await check(page, `resumes-${width}`);

    await visit(page, "/roles");
    await expect(page.getByRole("link", { name: /^Show details/ }).first()).toBeVisible();
    await check(page, `roles-${width}`);

    for (const s of ["journey", "findings", "stories", "lines"] as const) {
      await visit(page, `/resumes/${mainId}/check?step=${s}`);
      await expect(steps(page)).toBeVisible();
      await page.waitForLoadState("networkidle");
      await check(page, `check-${s}-${width}`);
    }

    for (const [opener, name] of [
      [/^Used by 1 role$/, /^Used by 1 role$/],
      [/^Findings you accepted · \d+ ›$/, /^Findings you accepted/],
      [/^What Strova checks ›$/, /^What Strova checks$/],
    ] as const) {
      await page.getByRole("button", { name: opener }).click();
      const drawer = page.getByRole("dialog", { name });
      await expect(drawer).toBeVisible();
      await check(page, `drawer-${String(name).replace(/\W+/g, "-")}-${width}`);
      await page.keyboard.press("Escape");
      await expect(drawer).toBeHidden();
    }
  });
}
