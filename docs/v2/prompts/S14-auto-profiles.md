# S14 · Auto-profiles

- **Branch:** `feat/v2-s14-auto-profiles`
- **Wave:** 1. **Waits for:** C1. Step 4 waits for S11.
- **Owns:** `apps/worker/src/strong_worker/profiles/` (new), `prompts/extractor/auto_profile*`,
  their fixtures, and one call in `apps/worker/src/strong_worker/gap/brief.py` (after S11 merges).
- **Requirement IDs:** AP-1, AP-2.

## Goal

Companies outside the curated list get a short summary in the interviewer's brief, once an
admin has reviewed it.

## Read first

- Spec: "Companies outside the launch list", IN-5, CompanyRequest, and the security rules on
  scraping and prompt injection.
- The existing job scraper in `apps/worker/src/strong_worker/inputs/`.

## Build

1. A worker job, queued when a job is added in generic mode, that:
   - fetches the careers and values pages on the posting's domain (reuse the scraper and its rate
     limits; same domain only)
   - runs the extractor with an `auto_profile` prompt to produce `AutoProfileSummary`
   - stores a `CompanyAutoProfile` as `pending`

   Keep one auto-profile per normalized company name, and reuse it when it exists.
2. Treat page text as untrusted: the prompt says so, and the existing injection filter runs
   first.
3. Add fake fixtures and tests that use recorded pages; no network in tests.
4. After S11 merges, change the brief builder:
   - In generic mode, it adds the summary of an `approved` auto-profile, labeled "auto-generated".
   - The summary never touches scoring weights (AP-2).
   - It runs only when the brief is built, never in the live loop.

## Done when

Tests cover AP-1 (the job creates a pending profile and reuses it per company) and AP-2 (only
approved profiles reach the brief, and weights are unchanged).
