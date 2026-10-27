# S22 · Story matching and the Proven rule

- **Branch:** `feat/v2-s22-story-matching`
- **Wave:** 2. **Waits for:** C2.
- **Owns:** `prompts/planner/story_fit*`, the story fields in `prompts/scorer/` (new versions
  only), `apps/worker/src/strong_worker/scoring/stories.py` (new) and one call to it in the
  scoring pipeline, a `story_fit` step in `apps/worker/src/strong_worker/gap/` (new file), and
  their fixtures.
- **Requirement IDs:** ST-5 (engine), ST-6 (engine), ST-7.

## Goal

The app knows which story fits each skill an interview tests, which story each answer used,
and when a story has proven itself.

## Read first

- Spec: "Rubric", "Hire signal", PL-3 (small models, one question at a time), PL-5, PL-6.
- `apps/worker/src/strong_worker/scoring/{scorer,jobs}.py`, `apps/worker/src/strong_worker/gap/`,
  `prompts/scorer/`, `prompts/planner/`.

## Build

1. Story fit (ST-5):
   - Inputs: the user's stories (title, parts, tags) and the skills a plan tests.
   - The planner role produces `StoryFitItem`s.
   - Run it when the plan page asks and the stories or the job changed. Cache the result with
     PL-6 provenance.
   - Expose a function the plan API (S10's `strong_api/plan/`) can call; S23 wires the endpoint
     in S10's module. Agree the function signature in your PR.
2. Story used (ST-6): after scoring, match each answer to at most one of the user's stories, and
   write `story_id` and `story_fix` (the answer's main fix, phrased for the story). Add the fix as
   a note on the story. Do it in a separate step after the scorecard, so scoring is never blocked
   or changed.
3. Proven rule (ST-7), in code, not in a prompt: a Realistic session answer with `story_id` set
   and a score of 3 or more marks the story `proven`. Coach and dev-profile sessions never count.
4. New prompt versions for any scorer change. Fixtures for every new reply. Small-tier variants
   that work one story at a time.

## Done when

Tests cover ST-5, ST-6 and ST-7, including "Coach mode never proves a story" and "the scorecard
is unchanged when story matching fails".
