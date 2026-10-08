# Strong Hire web app

React + Vite + TypeScript. The candidate-facing app: sign-in, onboarding, gap analysis, session
setup, live session, debrief, progress dashboard, account and paywall.

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

Every endpoint the web app uses exists in the API now, and the web app calls each one with the
typed client (`src/api/*.ts`). MSW mocks remain for front-end work without Docker, for Playwright,
and for Vitest. Production builds contain no mocks: `main.tsx` loads them only when
`import.meta.env.DEV` is true. Vitest tests check the mock responses against `openapi.json`.

The mocked voice join returns the URL `mock://voice`. For that URL, the live session page uses a
scripted interviewer (`src/session/mockVoice.ts`) instead of LiveKit.

Set `VITE_API_MOCKS` before `pnpm dev`:

| Value | What is mocked | Use it for |
| --- | --- | --- |
| `off` (default) | Nothing. The old value `planned` also means `off`. | The Docker stack |
| `all` | Everything, including sign-in and the voice room. No API needed. | Front-end work without Docker; Playwright |

The mock keeps its data in `localStorage`. To start over, run `strongHireMocks.reset()` in the
browser console.

## Live session (P10)

`src/session/LiveSessionPage.tsx` runs the voice interview:

1. The candidate checks the microphone. A blocked or missing microphone shows a message, and the
   session does not start.
2. The page waits until the interviewer brief is ready (`brief_ready`).
3. `POST /sessions/{id}/voice/join` starts the session and returns a LiveKit token. The page joins
   the room `session-<id>`, where the voice agent (apps/voice) runs the interview.
4. The agent sends the phase, its clock and its words on the data topic `session`. The page shows
   them as the phase list, the timer and captions. Coach commands go to the agent on topic `coach`.
5. If the connection drops, a banner offers Rejoin. The agent keeps the session for 2 minutes.
6. When the agent ends the session, or the candidate clicks End interview, the page opens the
   debrief, which waits for the score.

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
  as the free interview limit, the plan price and the minute cap live in the API config
  (`GET /billing/plan`, `GET /billing/usage`). The mocks copy them only to stay believable.
- Accessibility: every page sets its title and moves focus to its heading. Every input has a label.
  Errors use `role="alert"`. Charts have a table view.
