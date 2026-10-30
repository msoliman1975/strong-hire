# U09 · Debrief

- **Branch:** `feat/ux-u09-debrief`
- **Waits for:** U07, U08.
- **Owns:** `apps/web/src/pages/debrief/`, `DebriefPage.tsx` (v2 branch).
- **Requirement IDs:** DB-3, DB-4, DB-5, DB-6, SG-8 (UI).
- **Mockup routes:** `#debrief` before and after Apply (with Undo), with and without the Proven
  notice, for Behavioral and for another type.

## Goal

The debrief reads as Strova's verdict, the answers, then Strova's coaching with suggestions.

## Build

1. Header: "{company} · {type} · debrief", "Take N with Strova", mode, length, date; Back to the
   interview; Read the transcript (TR-1 link).
2. **Strova's verdict** (DB-3): teal top border, `<Strova mode="interviewing" size={72} />`,
   "Wearing the interviewer hat: {title} at {company}", hire signal with its colour and the change
   from the previous take (DB-1), met the bar (DB-2), readiness, rationale, the practice-estimate
   note.
3. **Answer by answer:** question, "Used your story X" (link) or why none, the fix, score of 4.
   Delivery metrics (DM-2) and the mini-interview note stay below the answers.
4. **Strova's coaching** (DB-4): violet top border, coaching avatar 72 px, "Back on your side: what
   to do next", one coaching sentence, then the session's suggestions from U08: tune a story with
   the before-and-after (Apply, Edit first opens the story with the edit prefilled, Dismiss; after
   Apply a notice with Undo), new story (Save as a story), missing skill (Craft it with Strova).
5. **Proven** (DB-5): when the take made a story Proven, the notice with
   `<Strova mode="celebrating" size={72} />`.
6. **Plan line** (DB-6): "Your plan updated: next is …" with Back to Home (text from the debrief
   API; hide the line until U11 fills it).
7. Keep the realism rating (L05) and QB-4's link only if they are still in the v2 debrief today;
   place them after the coaching card.

## Tests

DB-3, DB-4, DB-5, DB-6 and SG-8 (apply, edit first, dismiss, undo) each have a test; existing
DB-1, DB-2, DM-2, TR-1 and ST-2/ST-6 tests still pass (update their selectors as needed).

## Done when

Tests pass and every listed state passes the fidelity check at 1280 and 390.
