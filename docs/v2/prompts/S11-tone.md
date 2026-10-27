# S11 · Tone, end to end

- **Branch:** `feat/v2-s11-tone`
- **Wave:** 1. **Waits for:** C1. **Blocks:** step 4 of S14.
- **Owns:** tone validation in `apps/api/src/strong_api/sessions/`, the tone parts of
  `apps/worker/src/strong_worker/gap/brief.py`, `prompts/planner/interviewer_brief*`,
  `prompts/interviewer/turn*`, their gateway fixtures, and the evals that cover tone.
- **Requirement IDs:** TN-1, TN-2, TN-3.

## Goal

The tone the user picks shapes how the interviewer sounds, without changing what it probes or
how the session is scored.

## Read first

- Spec: IV-4, IV-5, "Interviewer brief", "Follow-up rules", and the profile's persona notes.
- `apps/worker/src/strong_worker/gap/brief.py`, `prompts/planner/interviewer_brief.v2.txt`,
  `prompts/interviewer/turn.v3.txt`, `prompts/README.md` (tiers and versioning).

## Build

1. The sessions API accepts and stores `tone` (C1's `SessionConfig.tone`); old clients get the
   default.
2. Brief builder: `as_company` keeps today's behavior (the persona tone from the profile, and
   Neutral in generic mode for TN-3). The other values replace the persona's tone line with a
   fixed description from the prompt file, so the planner never invents one. The rest of the
   persona (values, pace, how they close) stays.
3. Add new prompt versions (`interviewer_brief.v3`, `turn.v4`, and small-tier variants where they
   exist); never edit old versions. Tone words go only in the tone section. Difficulty keeps
   control of probes and pushback (TN-2).
4. Add fake fixtures for the new prompts, and a test that the scorer's input never includes the
   tone.

## Done when

Tests cover TN-1 to TN-3, including "tone never reaches the scorer", and the simulated-candidate
text sessions still pass.
