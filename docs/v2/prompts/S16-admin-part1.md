# S16 · Admin portal, part 1

- **Branch:** `feat/v2-s16-admin-part1`
- **Wave:** 1. **Waits for:** C1.
- **Owns:** `apps/admin/`, `apps/api/src/strong_api/admin/`.
- **Requirement IDs:** AD-3, AP-3.

## Goal

Admins can see how Part 1 is used and control which auto-profiles reach a brief.

## Read first

- `docs/admin-spec.md`, `apps/admin/src/pages/`, `apps/api/src/strong_api/admin/{router,metrics}.py`.

## Build

1. Metrics (AD-3): plan page views and the sessions started from it, and the tone and difficulty
   mix across sessions by week. Count from existing data where you can; add an event through the
   existing analytics path only if needed.
2. Auto-profile queue (AP-3): list pending profiles, show the summary and sources, approve, edit
   the summary, retire. Every action writes the audit log.
3. The `v2_enabled` switch on the controls page (FL-1), audited.

## Done when

API and admin tests cover AD-3, AP-3 and the audited flag switch.
