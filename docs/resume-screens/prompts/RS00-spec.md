# RS00 · Spec and loop on main

- **Branch:** `feat/rs-00-spec`
- **Waits for:** nothing.
- **Owns:** `docs/spec.md`, `docs/resume-screens/`, `docs/roadmap.md`.
- **Requirement IDs:** writes RSD-1 to RSD-16 into `docs/spec.md`. None is implemented here.

## Goal

Put the approved design and this loop on `main`, so every later task builds from it.

## Build

1. If `docs/resume-screens/` is missing on `main`, bring it, and the RMAP-9 roadmap entry, from
   the design branch:

   ```bash
   git checkout origin/claude/festive-albattani-kugrfd -- docs/resume-screens
   ```

   For `docs/roadmap.md`, add the RMAP-9 row and section by hand if `main` has changed since.
2. In `docs/spec.md`, add a section **"Resume screens redesign (RMAP-9)"** after the deep story
   crafting section. It has:
   - two or three sentences pointing to `docs/resume-screens/spec.md`;
   - the requirements table RSD-1 to RSD-16 in the spec's style (`| ID | Requirement | Priority |`).
3. Reword RM-3: "The resume check page shows story ideas, the breakdown, issues and resume-line
   suggestions (RMAP-9)." Change no other requirement text.
4. Update the spec's "Updated" date line.

## Done when

- The PR has only docs, and CI is green.
- Every ID RSD-1 to RSD-16 appears in `docs/spec.md` exactly once.
