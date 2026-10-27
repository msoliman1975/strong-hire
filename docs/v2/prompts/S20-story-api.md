# S20 · Story API, export and delete

- **Branch:** `feat/v2-s20-story-api`
- **Wave:** 2. **Waits for:** C2.
- **Owns:** `apps/api/src/strong_api/stories/` (new) and its router line, the story part of
  `apps/api/src/strong_api/account/` (export and delete).
- **Requirement IDs:** ST-1, ST-2 (API).

## Goal

A complete, owner-only API for stories that the web sessions (S21, S23, S31) build on.

## Read first

- C2's `Story` contract, `apps/api/src/strong_api/custom/` (the saved questions API is the
  closest pattern), `apps/api/src/strong_api/account/`.

## Build

1. CRUD: list (filter by status and skill), get, create, update by part, delete. Owner only, and
   scoped by `org_id` like every other user-owned table.
2. `POST /stories/from-answer` (ST-2): given a session and question ref, create a Draft story:
   - copy the candidate's answer text into the parts it fits; put all of it into `action` if no
     split is known yet (S22 may improve this)
   - tag it with that question's scored competencies
   - link the source
3. Notes: append a fix note (used by S22) and list notes.
4. Export includes stories and notes; delete removes them (ST-1, AC-1).
5. Keep the response models in `schemas/` via core contracts where they exist, or in the
   router's `schemas.py`, and publish the OpenAPI types the web uses (follow how other routers do it).

## Done when

Tests cover ST-1 (owner only, org scoping, export, delete) and ST-2.
