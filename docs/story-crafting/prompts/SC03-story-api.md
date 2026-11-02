# SC03 · API: edit, improve, organize, switch style

- **Branch:** `feat/sc-03-story-api`
- **Waits for:** SC02.
- **Owns:**
  - `apps/api/src/strong_api/stories/` and `coach/` (new endpoints);
  - `prompts/coach/improve_section*.txt`, `organize*.txt` and `rewrite_style*.txt`;
  - `prompts/coach/review.v2.txt`;
  - their fixtures.
- **Requirement IDs:** SC-10 (API), SC-11, SC-12, SC-13.

## Goal

Everything the story page needs to change an organized story, and the one-click move for classic
stories.

## Read first

- Spec: D-2, D-10 and D-11, and "Technical design → API".
- The review endpoint and `prompts/coach/review.v1.txt` (ST-11).
- The suggestion undo pattern (SG-2) for accept and reject.

## Build

1. **`PATCH /stories/{id}/outline`:** set, clear or reorder slots and steps typed by the user
   (`by_user`, no quotes). Validate them with `StoryOutline`, render the legacy columns, and
   recompute the status.
2. **`POST /stories/{id}/sections/{section}/improve`**, body `{note?}`. It returns a
   `SectionImprove`:
   - edits are before and after, from the user's words, with quotes, and applied only on accept;
   - questions mean facts are missing, and the UI opens a short session on that section.

   Add the accept and reject endpoints, or reuse the suggestion pattern with undo.
3. **`POST /stories/{id}/organize`** (classic stories only) returns an `OrganizeResult` preview,
   with no write. **`POST /stories/{id}/organize/accept`** sets the style to STAR, writes the
   outline and renders the legacy columns. Discard writes nothing (D-11).
4. **`POST /stories/{id}/style`**, body `{style, rewrite: bool}`. Without rewrite, it renames and
   moves slots in code (Task slots join Challenge in CARL, and the reverse), with no model call
   and no fact lost. With rewrite, it makes one model call (`StyleRewrite`), previews the result,
   and applies it on accept (D-2, SC-12).
5. **Review:** `review.v2.txt` works on the sections of a styled story; classic stories keep v1.
6. **Prompts and fake fixtures** for each new output type. Every prompt carries the D-6 rules.

## Done when

- Tests named for SC-10 to SC-13 pass. They cover:
  - an inline edit re-renders the legacy columns;
  - improve returns edits with quotes, or questions;
  - organize writes nothing until accept;
  - a switch without rewrite keeps every slot text and quote, round trip STAR to CARL to STAR;
  - a rewrite needs accept.
