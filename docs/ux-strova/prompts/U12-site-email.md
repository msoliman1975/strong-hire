# U12 · Strova on the site and in emails

- **Branch:** `feat/ux-u12-site-email`
- **Waits for:** U02, U11.
- **Owns:** `apps/site/` (header lockup, the "Meet Strova" section), the product email templates
  and sender names (debrief ready, plan reminders), the Strova PNGs from U02.
- **Requirement IDs:** SV-7 (site), SV-8, SV-9.
- **Reference:** spec section 4.5; the "Where Strova appears" panels "Site · hero" and
  "Email · reminder" on the archived identity board of the design canvas
  (https://claude.ai/artifact/KwPbVu6fzqAv3Kk4sGwv4J, page "Archive", board "Strova · identity and
  where it appears") for layout only; `reference/strova-avatar.html` for the avatar.

## Goal

Strova is introduced on the marketing site and signs the emails she sends, with the Strong Hire
brand unchanged.

## Read first

`apps/site/` (Astro, the v2 site from S41, its layout, header, sections and Lighthouse budgets in
`lighthouserc.json`); how product emails are built and sent (debrief ready, L06 reminders, U11's
reminder job, `email_logs`).

## Build

1. **Site header (SV-7):** the existing Strong Hire logo and name with "with Strova" in the muted
   colour. No new logo.
2. **Meet Strova (SV-8):** a section on the home page, below the hero or as the hero's second
   panel (choose what reads best with the current site, record it under Decisions): Strova's
   coaching avatar at 104 px (an inline SVG port of the component with its CSS animation, reduced
   motion respected), "Meet Strova, your interview partner.", "Strova reads your resume, helps you
   build the stories you'll tell, and rehearses the real interview with you.", and the primary
   call to action "Start with your resume" linking to sign-up. Optionally three small modes
   (analysing, coaching, interviewing) with one line each, if the page has room.
3. **Emails (SV-9):** the debrief-ready and plan-reminder emails use the sender display name
   "Strova from Strong Hire" and show the 64 px coaching PNG beside the Strong Hire logo, with alt
   text "Strova". Account emails (sign-in, confirmation, password reset, billing) keep "Strong
   Hire" and no avatar.
4. Lighthouse budgets stay green (the avatar adds no web font and no large image).

## Tests

SV-7 (site header lockup), SV-8 (section present with the copy and the avatar's accessible label;
reduced-motion rule present), SV-9 (sender name and avatar on Strova's emails, unchanged on
account emails).

## Done when

Site tests and Lighthouse pass in CI, email tests pass, and the site section matches the reference
panel and the avatar sheet (fidelity check at 1280 and 390).
