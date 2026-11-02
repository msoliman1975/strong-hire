# SC05 · Web: the organized story page

- **Branch:** `feat/sc-05-story-ui`
- **Waits for:** SC03, SC04.
- **Owns:** `apps/web/src/pages/stories/` (story page, workbench, review page),
  `apps/web/src/mocks/` (story handlers).
- **Requirement IDs:** SC-10, SC-11 (UI), SC-12 (UI), SC-13 (UI).

## Goal

The story reads as an organized outline. You can edit any slot in place, ask Strova to improve a
section, switch styles, and bring an old story into the new shape.

## Read first

- Spec: D-2, D-10 and D-11.
- `StoryPage.tsx`, `StoryView.tsx`, `StoryEditor.tsx`, `ReviewPage.tsx` and `StoryWorkbenchPage.tsx`.
- The ST-14 story page rules: status steps, versions, used-for notes, source.

## Build

1. **Outline view:** sections in style order, slots with their labels, action steps numbered, and
   the metric shown as before → after. Empty optional slots are shown quietly, and required empty
   slots are marked.
2. **Inline edit (SC-10):** click a slot to edit it, then Save or Cancel. Add, remove and reorder
   action steps, up to 5. The status steps update after a save.
3. **Improve with Strova (SC-11):** a button per section with an optional note. Edits show as
   before and after, with Accept or Reject. Questions open the coach session on that section.
4. **Switch style (SC-12):** "Switch to CARL/STAR", with a "Rewrite the wording too" option. A
   rewrite shows a preview to accept.
5. **Classic stories (SC-13):** today's five parts, plus an **Organize with Strova** banner that
   shows a preview with Accept or Discard.
6. **Review with Strova:** per-section notes and edits for styled stories.
7. **Mocks and tests** for each action and state.

## Done when

- The tests for SC-10 to SC-13 (UI) pass.
- The screen check is done for an organized STAR story, a CARL story, an inline edit, an improve
  preview, a switch preview, and a classic story with the organize preview, at 1280 and 390.
