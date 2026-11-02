# SC02 · API: outline engine and the craft turn

- **Branch:** `feat/sc-02-engine`
- **Waits for:** SC01.
- **Owns:**
  - `apps/api/src/strong_api/coach/` (engine, router, schemas);
  - `apps/api/src/strong_api/stories/` (the story out shape and readiness);
  - `prompts/coach/craft_turn*.txt`;
  - coach gateway fixtures.
- **Requirement IDs:** SC-3, SC-4, SC-5, SC-6, SC-14.

## Goal

A styled story can be crafted section by section in a text session. Its slots fill from the
user's words, its status follows the core slots, and the legacy columns stay right.

## Read first

- Spec: D-2 to D-7, D-12, "Sections and slots", the legacy column mapping, and "Technical design
  → API" and "Prompts".
- `apps/api/src/strong_api/coach/engine.py`: `asks()`, `opener()`, how turns merge parts and
  skills.
- `apps/api/src/strong_api/coach/router.py`.
- `prompts/coach/turn.v3.txt` and `turn_input.v2.txt`.
- The coach tests in `apps/api/tests`.

## Build

1. **Engine functions**, in code with no model:
   - `suggest_style(target_skill, question)`: the D-2 rule.
   - `next_ask(outline, style, skipped)`: returns the current section and its empty slots in the
     D-7 order. The order is Situation/Challenge, then Task (STAR only), Action, Result,
     Learning. Context slots are asked even when they are optional (D-5).
   - `apply(outline, reply)`: merges `slot_updates`, marks skips, and enforces quotes.
   - `ready(outline)`: SC-3.
   - `render_legacy(outline)`: SC-14, plain text with Markdown stripped.
2. **Session start** takes an optional `style`. A new story with a style gets an empty outline.
   The start response returns the suggested style when none was given, so the UI can preselect
   it. Existing classic sessions keep today's flow, unchanged.
3. **Styled turn:**
   - load `prompts/coach/craft_turn.v1.txt` and its `_input` file with `load_prompt`, giving the
     section, its empty slots, the skipped slots, the style, the coach style (gentle or direct)
     and the user's words;
   - call `gateway.complete("coach", …, output_type=CraftReply)`;
   - apply the reply, render the legacy columns, and recompute the status, the story fit (ST-5)
     and the versions as a part update does today;
   - store the prompt ref.
4. **The craft prompt** keeps every rule of `turn.v3.txt` (untrusted input, no new facts, verbatim
   quotes, one question, no grading words, no suggesting facts) and changes these:
   - It may reword for clarity (D-6).
   - Each section opens with one open question that can fill several slots. It follows up once on
     each empty slot it is given (D-7).
   - "skip" or "I can't share that" marks the slot skipped; "move on" ends the section.
   - When the engine says nothing is missing, it asks whether to sharpen a section or finish, as
     today.

   Add a `small` variant if the small tier needs simpler wording (PL-5).
5. **Fake fixtures** for `CraftReply`, plus recordings for a short scripted session in the coach
   conformance tests (CO-1).
6. **API out shape:** the story and session responses include `style`, `outline`, slot states and
   the current section. Regenerate the OpenAPI types for the web.

## Done when

- Tests named for SC-3 to SC-6 and SC-14 pass. They cover:
  - section order for STAR and CARL, and context slots asked once;
  - skip and move on;
  - quotes required on Strova slots;
  - Ready when exactly the core slots are filled;
  - `render_legacy` for both styles;
  - an existing reader (story fit, or the interviewer's story text) unchanged for a styled story.
- The existing coach and story tests still pass, and a classic session behaves as before.
