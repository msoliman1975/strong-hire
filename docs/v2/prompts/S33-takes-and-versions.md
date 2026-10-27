# S33 · Takes and story versions

- **Branch:** `feat/v2-s33-takes-versions`
- **Wave:** 3. **Waits for:** C3 and S30.
- **Owns:** `apps/api/src/strong_api/takes/` (new) and its router line,
  `apps/worker/src/strong_worker/scoring/takes.py` (new), `prompts/coach/story_versions*`, and
  their fixtures.
- **Requirement IDs:** CO-7, CO-8.

## Goal

Candidates practice a story and see it improve, and they get short and full versions written
from their own words.

## Read first

- `apps/worker/src/strong_worker/scoring/scorer.py` (one question at a time, PL-3), the rubric
  in the spec, and C3's `Take` and `StoryVersions`.

## Build

1. Takes (CO-7): `POST /stories/{id}/takes` with text (or a voice transcript from S32). A worker
   job scores it with the existing scorer, as one answer, on the story's skill tags, using the
   story's linked job level if there is one, or else the user's target level. Store per-skill
   1 to 4 scores with quotes and provenance. Reuse the scorer; do not fork its prompt.
2. Versions (CO-8): `POST /stories/{id}/versions` runs the coach role with `story_versions`,
   returning a 60-second and a full version. Each sentence must come from the story parts or the
   candidate's takes. Check the quotes in code and reject a version whose quotes are not found.
3. Takes never change a story's Draft or Proven status (only ST-7 does) and never count toward
   readiness.

## Done when

Tests cover CO-7 and CO-8, including "a version with an unsupported sentence is rejected".
