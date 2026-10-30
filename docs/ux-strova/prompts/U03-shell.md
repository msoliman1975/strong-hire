# U03 · Shell, navigation and terms

- **Branch:** `feat/ux-u03-shell`
- **Waits for:** U02.
- **Owns:** `apps/web/src/components/Layout.tsx`, `TopBar.tsx`, `copy.ts`, `labels.ts`, and copy
  changes in existing v2 screens; the session setup labels.
- **Requirement IDs:** NV-1, NV-2, NV-3, RH-5, SV-7 (app).
- **Mockup routes:** the shell on every screen (`#home` is enough to compare), `#interview` drawer
  for the mode labels.

## Goal

The app frame and the words match the approved design before the screens are rebuilt.

## Build

1. v2 left rail (when `v2_enabled`): exactly Home, "{First name}'s Resumes" (from the profile's
   full name, first word; "Your resumes" when empty), Target roles, Rehearsals with Strova (with an
   18 px `<Strova mode="interviewing" />`), Career Stories with Strova. Remove the separate coach
   button and the Question bank and Progress items from the v2 rail; keep their routes (NV-3).
   The current item uses the v2 selected style; on phones the rail scrolls horizontally.
2. Top bar: the existing `BrandMark` logo and "Strong Hire", then "with Strova" in the muted colour
   (the lockup, spec section 4.5; never the mockup's violet square), usage pill, initials button that
   opens Profile (SV-7, test it).
3. Terms (NV-2): replace "CV" with "resume" in all user-facing v2 copy (keep code identifiers and
   API names as they are), "session" with "take" where it means one run of an interview, and the
   mode label "Coach" with "Practice" (with its explanation: pause, ask for a hint, redo; does not
   count toward readiness) in setup, the live room and the debrief (RH-5). v1 copy stays.
4. Point the v2 routes at placeholders where later tasks will put the new screens, so nothing
   breaks in between: `/` Home (current Home v2 until U11), `/resumes`, `/roles` (Target roles
   list; the current Interviews v2 list until U07), `/rehearsals`, `/stories`.

## Tests

NV-1 (rail items and order, first-name label and fallback), NV-2 (no "CV" in rendered v2 screens:
a test that renders the v2 routes in mock mode and searches the text), NV-3 (questions and
progress routes still render), RH-5 (Practice label, stored value `coach`).

## Done when

Tests pass; the shell matches the mockup at 1280 and 390 (fidelity check on `#home`'s frame).
