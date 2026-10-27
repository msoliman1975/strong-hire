# S38 · Admin portal, part 3

- **Branch:** `feat/v2-s38-admin-part3`
- **Wave:** 3. **Waits for:** C3 and S25.
- **Owns:** `apps/admin/`, `apps/api/src/strong_api/admin/`.
- **Requirement IDs:** AD-5.

## Build

1. Coach: sessions and minutes per week, minutes against plan caps, cost per coach session from
   usage events, and the latest coach eval results (from S37's reports).
2. Readiness by skill across users, aggregate only.
3. Recruiter screen: show its brief and rubric in the existing session detail and replay pages.
4. The story radar runtime setting (if S36 merged), audited.

## Done when

Tests cover AD-5; no admin endpoint returns story text or coach conversation text outside the
existing replay rules.
