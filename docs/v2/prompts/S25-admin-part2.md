# S25 · Admin portal, part 2

- **Branch:** `feat/v2-s25-admin-part2`
- **Wave:** 2. **Waits for:** C2 and S16.
- **Owns:** `apps/admin/`, `apps/api/src/strong_api/admin/`.
- **Requirement IDs:** AD-4.

## Goal

Admins can see whether the story library is working, without reading anyone's stories.

## Build

1. Metrics: story save rate (share of users who saved at least one story within 30 days of their
   first debrief, which is a launch gate metric), stories per user, the Draft to Proven rate, and
   delivery metric trends by week. Aggregate only; no story text or titles anywhere in admin.
2. Support tools: an admin export or delete of a user's data includes stories, with the existing
   audit log.
3. A test that no admin endpoint returns story text.

## Done when

Tests cover AD-4 and the no-story-text rule.
