/**
 * Site-wide settings. Build-time environment variables switch the site at launch without code
 * changes (L04, docs/hosting.md "Marketing site"):
 *
 *   PUBLIC_APP_URL  where the app lives: https://app.getstronghire.com (Q9).
 *   PUBLIC_CTA      "waitlist" (before Dec 14, Q4) or "signup" (the main button goes to sign-up).
 */
export const APP_URL = (import.meta.env.PUBLIC_APP_URL ?? "https://app.getstronghire.com").replace(/\/$/, "");
export const CTA: "waitlist" | "signup" = import.meta.env.PUBLIC_CTA === "signup" ? "signup" : "waitlist";

export const SUPPORT_EMAIL = "support@getstronghire.com";
export const PRIVACY_EMAIL = "management@getstronghire.com";

/**
 * Q3: company names appear as plain text only, in this one list, always next to the notice.
 * Never in headings, page titles of general pages, domains, ads or social handles. Emptying the
 * list switches every page to "major tech companies".
 */
export const COMPANIES = [
  "Google",
  "Amazon",
  "Meta",
  "Microsoft",
  "Apple",
  "Nvidia",
  "Stripe",
  "Uber",
  "Netflix",
  "Airbnb",
  "Shopify",
];
export const COMPANY_COUNT = 39;
export const NOT_AFFILIATED =
  "Strong Hire is not affiliated with, endorsed by or sponsored by any company named on this site.";

/** RD-3: the same words as the app's readiness notice (apps/web/src/pages/plan/ReadinessApi.ts). */
export const READINESS_NOTICE =
  "Practice readiness is an estimate from your scored Realistic rehearsals. It is not a prediction of the hiring decision.";

/** Q3: verdicts are practice estimates, never a claim about a real company's decision. */
export const PRACTICE_NOTICE =
  "The verdict is a practice estimate from an AI interviewer. It is not a prediction of any company's hiring decision.";

export const signupUrl = (source?: string) =>
  `${APP_URL}/signin${source ? `?utm_source=${encodeURIComponent(source)}` : ""}`;
