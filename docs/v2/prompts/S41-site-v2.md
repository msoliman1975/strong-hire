# S41 · Marketing site for v2

- **Branch:** `feat/v2-s41-site`
- **Wave:** 4. **Waits for:** S01. Merge only when v2 launches.
- **Owns:** `apps/site/`.
- **Requirement IDs:** UI-3.

## Goal

The site tells the v2 story (two journeys: build your stories, prep for an interview) in the v2
visual language.

## Read first

- `apps/site/` (Astro, strict CSP: no inline styles or scripts), and the homepage built in PR #126.
- The App UX canvas, for screens to show as product images.

## Build

1. Move the site to S01's tokens (Geist and the v2 colors) through `@fontsource`, keeping the CSP.
2. Homepage: add the story library and coach sections, and keep the briefed-interviewer hero and
   the tone and difficulty demo (now both are user choices).
3. Keep the not-affiliated line, the practice notice and the privacy email as they are.
4. Lighthouse in CI must stay at its current scores.

## Done when

The site job is green (tests, astro check, build, Lighthouse), with screenshots at 1280px and
375px in the PR.
