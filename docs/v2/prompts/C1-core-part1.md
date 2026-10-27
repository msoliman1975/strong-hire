# C1 · Core changes for Part 1

- **Branch:** `feat/v2-c1-core-part1`
- **Wave:** 0. **Waits for:** nothing. **Blocks:** S10, S11, S12, S14, S16, C2.
- **Owns:** `packages/core`, `schemas/`.
- **Requirement IDs:** TN-1 (contract), AP-1 (model), FL-1.

## Goal

One small shared PR with every contract, model and migration Part 1 needs, merged before the
Part 1 feature sessions start.

## Read first

- `CLAUDE.md` sections "Contracts and schemas" and "Migration rules".
- `packages/core/src/strong_core/schemas/{enums,session,profile}.py`,
  `packages/core/src/strong_core/db/models.py`, `packages/core/src/strong_core/runtime_settings.py`.

## Build

1. `Tone` enum: `as_company`, `warm`, `neutral`, `direct`. `SessionConfig.tone: Tone`, default
   `as_company`. `Session.tone` column with a default so old rows read as `as_company`.
   The brief's existing `tone: str` stays the text the interviewer reads; S11 fills it.
2. `CompanyAutoProfile` model: company name, normalized name, source host, summary text,
   sources list, status (`pending`, `approved`, `retired`), reviewed_by, reviewed_at, and the
   PL-6 provenance fields. Not user-owned (no `org_id`); say why in the docstring.
   Contract `AutoProfileSummary` for the extractor output (summary, values mentioned, interview
   process notes, sources), rejecting unknown fields.
3. Runtime setting `v2_enabled: bool = False` (FL-1), readable by the web app through the
   existing settings or controls endpoint (find how `custom_interview_access` reaches the web).
4. One Alembic migration with a working `downgrade()`. Regenerate `schemas/`.
5. A fake fixture `AutoProfileSummary.json` for the extractor role that validates.

## Done when

`alembic upgrade`, `alembic check`, downgrade to base and upgrade again pass locally; schema
freshness passes; tests cover TN-1 defaulting and FL-1 default off.
