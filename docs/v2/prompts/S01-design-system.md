# S01 · v2 design system and app shell

- **Branch:** `feat/v2-s01-design-system`
- **Wave:** 0. **Waits for:** nothing.
- **Owns:** `apps/web/src/styles.css`, `apps/web/src/theme/` (new), `apps/web/src/components/Layout.tsx`,
  `apps/web/src/components/BrandMark.tsx`, `apps/web/src/components/ui.tsx`, web font packages in
  `apps/web/package.json`, `apps/admin/src/styles.css` and `apps/admin/src/styles/`.
- **Requirement IDs:** UI-1, UI-2.

## Goal

Replace the current Strong Hire look in the app with the v2 visual language, so every later UI
session builds on its tokens and components instead of inventing styles.

## Read first

- The App UX canvas, all six screens (link in `00-common.md`). Take the exact values from them:
  - Fonts: Geist and Geist Mono.
  - Colors: ground #f4f3f8, ink #17161f, muted #5e5b6b, line #e2e0ea; action violet #5332e6
    (soft #eeeafe); interview prep teal #0b6e8c (soft #e0f2f7).
  - Story parts: context #5e5b6b, stakes #a34d00, action #5332e6, result #12775a, reflection #0b6e8c.
  - Live room: dark #0e0d14 / #1a1824.
- `apps/web/src/styles.css`, `apps/web/src/components/`, `apps/web/src/architecture.test.ts`.
- `apps/site` uses a strict CSP; the app may differ. Check `infra/` Caddy config for the app's CSP
  before loading fonts. Use `@fontsource` packages, not Google Fonts.

## Build

1. Tokens as CSS custom properties in `apps/web/src/theme/tokens.css`, imported by `styles.css`.
   Keep the existing token names working as aliases so v1 pages keep rendering, then restyle them.
2. Components in `ui.tsx` restyled: buttons (primary violet, secondary outline), cards, pills,
   segmented control, tag, meter (rubric 1 to 4), status badge, page header.
3. New shared pieces for later sessions: `StoryPartChip` (color plus text label, never color
   alone), `CountdownBadge`, `CoachLine` (the coach's one-sentence message with its mark).
4. `Layout.tsx`: the left rail nav from the canvas (UI-2). "Stories" is hidden unless
   `v2_enabled` is on; until C1 merges, read it from a stubbed hook `useFeature("v2_enabled")`
   in `apps/web/src/theme/features.ts` that C1's API wires up later.
5. `BrandMark.tsx`: the new mark from the canvas (black rounded square with a check). Keep the
   wordmark text "Strong Hire".
6. Apply the same tokens to `apps/admin` so the admin portal matches; admin keeps its own layout.
7. Check every existing page at 1280px and 375px for broken layout and contrast; fix in styles,
   not in page files you do not own. List any page that needs a page-level fix in the PR.

## Done when

Existing web and admin tests pass, a test covers UI-2 (Stories hidden when the flag is off), and
the PR includes before and after screenshots of Home, the debrief and the live room.
