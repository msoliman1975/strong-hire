/**
 * Settings for the marketing site. Each one is a single switch, so launch-day changes are
 * one-line edits (or one environment variable at build time).
 */

export const SITE_URL = import.meta.env.SITE ?? "https://getstronghire.com";

/** Where the app lives after the move (Q9). */
export const APP_URL = import.meta.env.PUBLIC_APP_URL ?? "https://app.getstronghire.com";

/**
 * Q4: what the main button does. "waitlist" until sign-ups open on Dec 14, then "signup".
 * Build with PUBLIC_CTA_MODE=signup to switch.
 */
export const CTA_MODE: "waitlist" | "signup" =
  import.meta.env.PUBLIC_CTA_MODE === "signup" ? "signup" : "waitlist";

export const LAUNCH_DATE_TEXT = "December 14";

export const cta =
  CTA_MODE === "signup"
    ? { label: "Start free", href: `${APP_URL}/signup`, note: "Free to start. No card needed." }
    : { label: "Join the beta waitlist", href: "/waitlist", note: `Sign-ups open ${LAUNCH_DATE_TEXT}. Free to start.` };

/**
 * Q3: company names appear as plain text only, always next to the not-affiliated notice.
 * Never logos, brand colors, or words like "official" or "partner".
 * If the lawyer says no, set SHOW_COMPANY_NAMES to false: every page then says
 * "21 major tech companies" instead.
 */
export const SHOW_COMPANY_NAMES = true;

export const COMPANIES = [
  "Google", "Amazon", "Microsoft", "Meta", "Apple", "Netflix", "Nvidia", "Salesforce", "Uber",
  "Stripe", "OpenAI", "Anthropic", "Airbnb", "Shopify", "LinkedIn", "Oracle", "Adobe",
  "Databricks", "Snowflake", "Atlassian", "Walmart",
] as const;

export const NOT_AFFILIATED =
  "Strong Hire is not affiliated with, endorsed by, or sponsored by any company named on this site. Names are used only to describe the interviews you can practice for.";

export const PRACTICE_ESTIMATE =
  "A hire signal is a practice estimate from our scorer. It is not a prediction of any company's hiring decision.";

/** Q11: legal pages are plain-language drafts until the lawyer's texts replace them. */
export const LEGAL_DRAFT = true;

export const CONTACT = {
  support: "support@getstronghire.com",
  privacy: "privacy@getstronghire.com",
  legal: "legal@getstronghire.com",
};
