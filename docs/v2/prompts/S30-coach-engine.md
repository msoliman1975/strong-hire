# S30 · Coach engine (text)

- **Branch:** `feat/v2-s30-coach-engine`
- **Wave:** 3. **Waits for:** C3. **Blocks:** S32 and S33; S31 for live data.
- **Owns:** `apps/api/src/strong_api/coach/` (new) and its router line, `prompts/coach/` (except
  `story_versions*`), the coach gateway fixtures.
- **Requirement IDs:** CO-2, CO-3, CO-4, CO-5.

## Goal

A text conversation in which the coach helps a candidate build one story, and the story's parts
fill in as they talk. Canvas board: A1 Coach session.

## Read first

- Spec: "Follow-up rules" (IV-3), PL-3, PL-5, PL-6, PL-7, BL-1 (minutes).
- `apps/api/src/strong_api/sessions/` and the text session path (PL-7) for the patterns to reuse.
- `prompts/interviewer/` for prompt style, and `prompts/README.md`.
- The plan doc's risk: "The coach writes the story for the candidate".

## Build

1. API:
   - start a coach session, for a new story or an existing one, with an optional target skill
     and an optional link to a plan page gap
   - send a candidate turn and get a `CoachReply`
   - end the session
   - list sessions for a story
2. Each reply updates the story's parts only with what the candidate said, saved through C2's
   Story model; the reply's quotes back every part (CO-3).
3. The coach asks for one missing thing at a time, using the IV-3 rules: the candidate's own
   role, a measurable result, a concrete example, trade-offs (CO-4).
4. Style `gentle` or `direct` is a section of the prompt only (CO-5).
5. Prompts:
   - `prompts/coach/turn.v1.txt` and `turn_input.v1.txt`, plus small-tier variants
   - a server-side template only; the candidate's text is data
   - the existing input checks for off-topic or abusive turns apply (IV-12 rules)
6. Record minutes and usage events like a session. Do not change billing caps.
7. Fake fixtures for a scripted three-turn conversation.

## Done when

API tests cover CO-2 to CO-5 on the fake model, including "a part is never filled without a
quote from the candidate".
