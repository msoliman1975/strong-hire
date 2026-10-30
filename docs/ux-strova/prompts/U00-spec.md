# U00 · Spec and package on main

- **Branch:** `feat/ux-u00-spec`
- **Waits for:** nothing.
- **Owns:** `docs/spec.md`, `docs/ux-strova/`.
- **Requirement IDs:** writes all of them into the spec (none are implemented here).

## Goal

Put the approved design on `main` so every later task builds from it.

## Build

1. If `docs/ux-strova/` is not on `main`, bring it from `origin/claude/eloquent-pascal-7ygux4`
   (`git checkout origin/claude/eloquent-pascal-7ygux4 -- docs/ux-strova`). Do not create or change
   `.claude/settings.json`; that is the user's decision.
2. In `docs/spec.md`, add a section **"v2.1 UX with Strova"** after the v2.0 requirements:
   - two or three sentences on what changes (resume first, Strova, roles and interviews, takes,
     one personal plan, suggestions), pointing to `docs/ux-strova/ux-spec.md` and the mockups;
   - the requirement tables from `ux-spec.md` section 12, in the spec's table style
     (`| ID | Requirement | Priority |`, all P0);
   - a note under the v2 journeys that Journey A and B now follow the flows in `ux-spec.md`.
3. Update the spec's "Updated" date line.
4. Do not change any requirement text of v1 or v2.0.

## Done when

The PR has only docs, CI is green, and every ID from `ux-spec.md` section 12
appears in `docs/spec.md` exactly once.
