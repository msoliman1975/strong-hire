# S13 · Transcript view

- **Branch:** `feat/v2-s13-transcript`
- **Wave:** 1. **Waits for:** S01.
- **Owns:** `apps/api/src/strong_api/reports/transcript.py` (new) and its route line,
  `apps/web/src/pages/transcript/` (new), and the transcript part of export in
  `apps/api/src/strong_api/account/` if it is not already there.
- **Requirement IDs:** TR-1, TR-2.

## Goal

Candidates can read what they and the interviewer said in any finished session.

## Read first

- Spec: the Turn entity, AC-1 and "Data handling" (audio is never kept).
- `apps/api/src/strong_api/reports/`.

## Build

1. `GET /sessions/{id}/transcript`: turns in order, with speaker, phase, text and time offset,
   grouped by question. Only the owner can read it; admins keep using the existing replay page.
2. Web page `/sessions/:id/transcript`, linked from the debrief ("Read the transcript"). If S12
   has not merged yet, add the link to the current debrief and say so in the PR.
3. Check that the AC-1 export includes turns and that delete removes them, and add a test either
   way (TR-2).

## Done when

Tests cover TR-1 (owner only, 404 for anyone else) and TR-2.
