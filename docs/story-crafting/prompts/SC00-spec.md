# SC00 · Spec and loop on main

- **Branch:** `feat/sc-00-spec`
- **Waits for:** nothing.
- **Owns:** `docs/spec.md`, `docs/story-crafting-spec.md`, `docs/story-crafting/`,
  `docs/roadmap.md`.
- **Requirement IDs:** writes SC-1 to SC-18 into `docs/spec.md`. None is implemented here.

## Goal

Put the agreed design and this loop on `main`, so every later task builds from it.

## Build

1. If `docs/story-crafting-spec.md` or `docs/story-crafting/` is missing on `main`, bring them,
   and the RMAP-7 and RMAP-8 roadmap entries, from the design branch:
   `git checkout origin/claude/confident-keller-wko1r5 -- docs/story-crafting-spec.md docs/story-crafting`.
   For `docs/roadmap.md`, take the design branch's file only if `main` has nothing newer;
   otherwise add the RMAP-7 and RMAP-8 rows and sections by hand.
2. In `docs/spec.md`, add a section **"Deep story crafting (RMAP-8)"** after the v2.1 UX
   section:
   - two or three sentences on what changes, pointing to `docs/story-crafting-spec.md`;
   - the requirements table SC-1 to SC-18, in the spec's table style (`| ID | Requirement |
     Priority |`);
   - a note under CO-9 that crafting may now reword, but never add a fact (D-6, SC-15).
3. Update the spec's "Updated" date line.
4. Do not change any other requirement text.

## Done when

- The PR has only docs and CI is green.
- Every ID SC-1 to SC-18 appears in `docs/spec.md` exactly once.
