# PT02: Consent toggle, deletion requests, text turn content

Read `00-common.md` and `PT-common.md` first.

- **Branch:** `feat/pt-02-api-web`
- **Waits for:** PT01
- **Folders:** `apps/api/src/strong_api/account`, `apps/api/src/strong_api/sessions`, `apps/web`
  (account page, API types, mocks), their tests
- **Requirement IDs:** LT-20, LT-21 (text), LT-24, LT-25

## Build

1. **Consent API (LT-20):** `PUT /account/tracing-consent {tracing_consent}`, refused (404) while
   `LLM_TRACING_PROD_CONTENT` is off. The account read returns `tracing_consent` and
   `tracing_consent_available`. Each change sets `tracing_consent_at` and writes
   `account.tracing_consent_changed` to the audit log.
2. **Withdrawal (LT-24):** turning it off queues `delete_traces(org_id, scope="content")`.
3. **Account deletion (LT-25):** queues `delete_traces(org_id, scope="all")` with the file job.
4. **Text turns (LT-21):** after each text turn, when the turn's tags say `turn_content`, call
   `record_turn_content` with the candidate's text and the interviewer's reply from the turns,
   scrubbed by the org's scrubber.
5. **Web:** the toggle on the account page under the training-data toggle, shown only when
   `tracing_consent_available`; wording from `docs/llm-tracing/phase2-gates.md` gate 2 (marked
   draft until the lawyer approves). MSW mocks; screen check at 1280 and 390, axe clean.

## Tests

- LT-20: off by default; hidden and refused while the flag is off; audit row on each change.
- LT-21: a consenting user's text turn writes a scrubbed `turn.content` trace; a non-consenting
  user's writes none; the metadata trace holds no text either way.
- LT-24: withdrawal queues a `content` deletion and the next turn writes no content.
- LT-25: account deletion queues an `all` deletion.
