# PT06: End-to-end check, gates and report

Read `00-common.md` and `PT-common.md` first.

- **Branch:** `feat/pt-06-e2e`
- **Waits for:** PT01 to PT05
- **Folders:** tests in any app, `docs/llm-tracing/`
- **Requirement IDs:** LT-30; verifies LT-16 to LT-31

## Build

1. A test map: for each of LT-16 to LT-31, the test that covers it. Add one for any ID with none.
2. One integration test, all fake: with both flags on, a consenting and a non-consenting real
   user each take a text session. Check: metadata traces for both, with no text; `turn.content`
   only for the consenting user, scrubbed; withdrawal then deletes the content traces through the
   job and keeps metadata; account deletion removes the rest.
3. LT-30: a test that both flags default off in code, compose files and example env files.
4. The PR lists the state of each gate in `phase2-gates.md`.
