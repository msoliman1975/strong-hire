# C3 · Core changes for Part 3

- **Branch:** `feat/v2-c3-core-part3`
- **Wave:** 3. Start it as soon as C2 merges, while wave 2 runs. **Waits for:** C2.
  **Blocks:** S30, S33, S34, S35, S37, S38.
- **Owns:** `packages/core`, `schemas/`, `config/` (the coach role only). This is the small P1
  config change the gateway rule requires.
- **Requirement IDs:** CO-1, RS-1 (enum), RD-1 (contract).

## Goal

One small shared PR that adds the coach role, the coach and take data, the recruiter screen type,
and the readiness contract.

## Read first

- `CLAUDE.md`, "The gateway rule" and "The fake-model rule".
- `packages/core/src/strong_core/gateway/`, `config/models.*.yaml`, `config/litellm.*.yaml`,
  `config/README.md`.
- `packages/core/src/strong_core/schemas/enums.py` (`InterviewType`, `COMPETENCIES_BY_TYPE`).

## Build

1. Gateway role `coach`, mapped in every `config/models.<profile>.yaml`. Point it at an existing
   alias for now (the interviewer's, or a smaller one where a profile has one), so no new model
   id is needed. Add it to the conformance suite's role list.
2. Contracts, all rejecting unknown fields:
   - `CoachReply`: message to the candidate, updated story parts (only the parts the candidate's
     own words support), the missing parts, candidate skill tags, and a `quotes` list of the
     candidate's words each part came from
   - `StoryVersions`: a 60-second version and a full version, each with quotes
   - `Readiness`: per skill, a score from 0 to 100 or `not_enough_data`, sessions counted, and an
     as-of date
3. Models, all user-owned with `org_id` and in `USER_OWNED_TABLES`:
   - `CoachSession`: story_id, style `gentle` or `direct`, channel, status, minutes, and the PL-6
     provenance fields
   - `CoachTurn`: transcript only, like Turn
   - `Take`: story_id, channel, text, duration, per-skill scores, scorer provenance
4. `InterviewType.RECRUITER_SCREEN` with its entry in `COMPETENCIES_BY_TYPE`: motivation, role fit,
   communication, and logistics and expectations. Add new `Competency` values only if needed,
   and update every exhaustive match the type checker finds.
5. One migration with a working `downgrade()`, `down_revision` = C2's. Regenerate `schemas/`.
   Add fake fixtures `CoachReply.json` and `StoryVersions.json` for the coach role.

## Done when

The migration checks and conformance tests pass, the model-name scan passes, and every
`<OutputType>.json` fixture validates.
