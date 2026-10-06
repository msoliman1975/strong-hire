# Strong Hire web app

React + Vite + TypeScript. The candidate-facing app: sign-in, onboarding, gap analysis, session
setup, live session (placeholder until P10), debrief, progress dashboard, account and paywall.

## Commands

```powershell
pnpm install
pnpm dev          # http://localhost:5180, API calls go to /api (proxied to the API on 8700)
pnpm test         # Vitest
pnpm test:e2e     # Playwright smoke tests (starts its own dev server with all mocks on)
pnpm lint
pnpm typecheck
pnpm gen:api      # regenerate src/api/schema.gen.ts from openapi.json
```

## Mocks (MSW)

Some screens need endpoints that later workstreams build. `src/api/planned.ts` lists them, with
the owner of each. MSW mocks them in development so every screen works today. Production builds
contain no mocks: `main.tsx` loads them only when `import.meta.env.DEV` is true.

The job target and resume endpoints (P2), their lists, and the gap analysis endpoints (P6) are
real. `src/api/inputs.ts` and `src/api/gap.ts` call them with the typed client. Their mocks use the
same paths and shapes, and a Vitest test checks the mock responses against `openapi.json`.

The debrief and progress endpoints (P8) are real too. `src/api/scoring.ts` calls them with the
typed client. Their mocks (`scoringHandlers`) stay on in every mode while sessions are mocked (P7),
because the API does not know a mocked session.

Set `VITE_API_MOCKS` before `pnpm dev`:

| Value | What is mocked | Use it for |
| --- | --- | --- |
| `planned` (default) | Only endpoints the API does not have yet. Sign-in, job targets, resumes and gap analysis use the real API; the mock keeps a copy of each job target, resume and gap analysis for the planned endpoints. | The Docker stack |
| `all` | Everything, including sign-in. No API needed. | Front-end work without Docker; Playwright |
| `off` | Nothing. | When every endpoint exists |

The mock keeps its data in `localStorage`. To start over, run `strongHireMocks.reset()` in the
browser console.

When a workstream builds a planned endpoint, it moves the caller from `request()` to the typed
`apiClient`, regenerates the types, and deletes the matching mock handler.

## Typed API client

`openapi.json` comes from the FastAPI app plus every shared contract in `strong_core.schemas`.
Regenerate both files after an API or contract change:

```powershell
uv run python apps/web/scripts/export_openapi.py
pnpm --dir apps/web gen:api
```

A pytest test fails when `openapi.json` is stale. A Vitest test fails when `schema.gen.ts` is stale.
Another Vitest test validates every mock payload against the JSON Schemas in `/schemas`.

## Rules

- No business logic in the web app. It shows what the API returns and validates forms. Rules such
  as the free interview limit live in the API (and, until then, in the mock only).
- Accessibility: every page sets its title and moves focus to its heading. Every input has a label.
  Errors use `role="alert"`. Charts have a table view.
