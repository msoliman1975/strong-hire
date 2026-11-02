# SC06 · Flow check and skill hints

- **Branch:** `feat/sc-06-flow-hints`
- **Waits for:** SC05.
- **Owns:**
  - `apps/api` (coach and stories: flow and hints);
  - `prompts/coach/flow_check*.txt` and its fixtures;
  - `apps/web` (session panel and story page: flags and hints).
- **Requirement IDs:** SC-8, SC-9.

## Goal

Strova points out where the story doesn't hang together, and which other skills it could show.
Both are advisory, and neither changes the status.

## Read first

- Spec: D-8 and D-9, SC-8 and SC-9.
- The story-fit data (`role_story_fits`, ST-5) and the user's target roles' skills.

## Build

1. **Flow check (SC-9):**
   - `POST /stories/{id}/flow-check` makes one model call (`FlowCheck`) and stores the result in
     `flow_json` with the slot texts it saw;
   - it runs once the core slots are filled, at the end of a styled session, and with Review;
   - a dismissed flag key stays dismissed until a slot it cites changes;
   - the prompt checks the five flag types and asks a question for each flag, never suggesting a
     fact.
2. **Skill hints (SC-8):**
   - once the core slots are filled, the craft turn may return `hints` (skill and why), from the
     story only;
   - the API orders them, gap skills of the user's target roles first, keeps at most three, and
     stores them in `hints_json`;
   - **Deepen** adds a short "Also shows {skill}" section to this story through a mini session
     (with quotes); **Not now** dismisses the hint.
3. **UI:**
   - flags on the story page and at the end of the session, each with **Ask me about it** (a
     short session on that slot) and **Dismiss**;
   - hints in the session panel and on the story page, with **Deepen** and **Not now**;
   - nothing blocks the status.
4. **Fake fixtures** with one flag of each type, and hints.

## Done when

- Tests named for SC-8 and SC-9 pass. They cover:
  - each flag type round-trips;
  - a dismissed flag doesn't return, and returns after its slot changes;
  - the status is unchanged by flags;
  - hints are ordered by gaps and capped at three.
- The screen check is done for flags and hints, at 1280 and 390.
