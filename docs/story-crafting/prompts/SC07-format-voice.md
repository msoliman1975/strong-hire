# SC07 · Formatting and the voice light flow

- **Branch:** `feat/sc-07-format-voice`
- **Waits for:** SC06.
- **Owns:**
  - `apps/web` (a shared Markdown editor and renderer, used by the reply box and slot editors);
  - `apps/api` (strip Markdown in `render_legacy`, quotes and word counts);
  - `apps/voice` (the styled coach flow, lighter).
- **Requirement IDs:** SC-16, SC-18.

## Goal

Users can format what they write. Voice crafting fills the same slots with a lighter flow.

## Read first

- Spec: D-13, D-14, SC-16 and SC-18.
- The coach voice path: `useCoachVoice.ts`, the voice agent's coach mode, and CO-6.

## Build

1. **Markdown editor (SC-18):**
   - a small toolbar for bold, italic, bullets and numbers, plus Ctrl+B and Ctrl+I, over a
     textarea;
   - a safe renderer for a Markdown subset with no raw HTML; prefer a small existing library (pin
     a version at least two weeks old) and check the bundle size;
   - pasting rich text converts to Markdown;
   - use it in the reply box and the slot editors.
2. **Plain text where it matters:** strip Markdown before:
   - `render_legacy`;
   - quote matching (quotes are matched on plain text);
   - word counts and limits (R3);
   - anything sent to TTS or the scorer.

   Test each one.
3. **Voice light flow (SC-16):** voice coach sessions on styled stories use the same engine and
   prompt in a voice mode:
   - opening questions per section;
   - follow-ups only on required slots;
   - no flow check during the call; it runs after the call.

   Classic voice sessions keep working.

## Done when

- Tests named for SC-16 and SC-18 pass, and the voice path has a test with a fake transcript.
- The screen check is done for the formatted reply box and slot editor, at 1280 and 390.
