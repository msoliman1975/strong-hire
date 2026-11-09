# LLM tracing phase 2: test map (LT-16 to LT-31)

Each requirement and the tests that cover it. All tests run with `MODEL_PROFILE=fake`; no test
reaches MLflow or a model. `packages/core/tests/test_tracing_gates.py` checks that every ID below
is listed and that every file named here exists.

The end-to-end test `apps/api/tests/test_tracing_e2e.py` runs two real users through one flow
with both flags on: one consents and one does not. Each takes a text session. Then the
consenting user withdraws, and finally deletes the account. It covers LT-16, LT-17, LT-18 and
LT-21 to LT-25 together.

| ID | What | Tests |
| --- | --- | --- |
| LT-16 | Real users traced only behind `LLM_TRACING_PROD` | `packages/core/tests/test_tracing_prod.py` (`test_lt16_*`), `apps/api/tests/test_tracing_e2e.py` |
| LT-17 | Metadata mode: no text, no hash, no error message | `packages/core/tests/test_tracing_prod.py` (`test_lt17_*`), `apps/api/tests/test_tracing_e2e.py` |
| LT-18 | `org_id`, `session_id` and the other tags on every production trace | `packages/core/tests/test_tracing_prod.py` (`test_lt18_*`), `apps/api/tests/test_tracing_e2e.py` |
| LT-19 | Stable per-session sampling; the pause setting and its Controls switch | `packages/core/tests/test_tracing_prod.py` (`test_lt19_*`), `apps/api/tests/test_admin_mlflow_auth.py` (`test_lt19_*`), `apps/admin/src/pages/ControlsPage.test.tsx` |
| LT-20 | `tracing_consent`, off by default, toggle only behind the content flag, audited | `packages/core/tests/test_tracing_prod.py` (`test_lt20_*`), `apps/api/tests/test_tracing_consent.py` (`test_lt20_*`), `apps/web/src/pages/AccountPage.test.tsx` |
| LT-21 | Text and voice turn content for consenting users only | `apps/api/tests/test_tracing_consent.py` (`test_lt21_*`), `apps/voice/tests/test_voice_tracing.py` (`test_lt21_*`), `apps/api/tests/test_tracing_e2e.py` |
| LT-22 | Scrubbing: emails, phones, name, companies | `packages/core/tests/test_tracing_prod.py` (`test_lt22_*`), `apps/api/tests/test_tracing_e2e.py` |
| LT-23 | Content is its own `turn.content` trace tagged `content=turns` | `packages/core/tests/test_tracing_prod.py` (`test_lt23_*`), `apps/api/tests/test_tracing_e2e.py` |
| LT-24 | Withdrawal stops content at the next turn and deletes kept content | `apps/api/tests/test_tracing_consent.py` (`test_lt24_*`), `apps/voice/tests/test_voice_tracing.py` (`test_lt24_*`), `packages/core/tests/test_tracing_prod.py` (`test_lt24_lt25_*`), `apps/web/src/pages/AccountPage.test.tsx`, `apps/api/tests/test_tracing_e2e.py` |
| LT-25 | Account deletion deletes all the org's traces | `apps/api/tests/test_tracing_consent.py` (`test_lt25_*`), `packages/core/tests/test_tracing_prod.py` (`test_lt25_*`), `apps/api/tests/test_tracing_e2e.py` |
| LT-26 | `delete_traces` job, retries, audit row, overdue alert | `apps/worker/tests/test_trace_deletion.py` (`test_lt26_*`) |
| LT-27 | Retention: content 30 days, the rest 90 days | `packages/core/tests/test_tracing_prod.py` (`test_lt27_*`), `apps/worker/tests/test_trace_deletion.py` (`test_lt27_*`) |
| LT-28 | MLflow only behind the admin sign-in; the sim token; no basic auth | `apps/api/tests/test_admin_mlflow_auth.py` (`test_lt28_*`), `packages/core/tests/test_infra_mlflow.py` (`test_lt28_*`) |
| LT-29 | `admin.trace_viewed` for trace reads | `apps/api/tests/test_admin_mlflow_auth.py` (`test_lt29_*`) |
| LT-30 | Both flags off by default everywhere; the gates document | `packages/core/tests/test_tracing_gates.py` |
| LT-31 | A failed lookup means not traced, never an error | `packages/core/tests/test_tracing_prod.py` (`test_lt31_*`) |

## Not covered by a test

- LT-26, the alert email itself: the rule is seeded and its reading is tested. Sending goes
  through the shared alert engine, which has its own tests.
- LT-27, MLflow's database in the 30-day backup rotation (D-14): an operations fact, checked on
  the server, not in code.
- LT-28, the MLflow UI under the relaxed CSP: checked by hand in Chromium against MLflow 3.17.2
  (no CSP violations; trace list and trace view load). `caddy validate` runs in CI.
