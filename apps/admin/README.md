# Strong Hire Admin (`apps/admin`)

The admin app (D-1 in `docs/admin-spec.md`), served at `admin.<domain>`. React + Vite +
TypeScript, with the same tooling and versions as `apps/web`. It shares no runtime code with
`apps/web`; a few UI pieces are copied on purpose.

```powershell
pnpm --dir apps/admin install
pnpm --dir apps/admin dev        # http://localhost:5181, /api proxied to http://localhost:8700
pnpm --dir apps/admin test       # Vitest + Testing Library, every request mocked with MSW
pnpm --dir apps/admin lint
pnpm --dir apps/admin typecheck
pnpm --dir apps/admin build      # dist/, served by Caddy from /srv/admin
```

Set `VITE_API_MOCKS=all` to run without the API (seeded data, see `src/mocks/browser.ts`).

## Layout

| Path | Contents |
| --- | --- |
| `src/App.tsx` | Routes. New sections add their routes under `<Shell />`. |
| `src/components/Shell.tsx` | Sidebar, nav (`SECTIONS`), environment label, sign-out, and the admin check (AA-4) |
| `src/components/ui.tsx` | `PageHead`, `Loading`, `ErrorNotice` |
| `src/components/charts.tsx`, `metrics.tsx` | Inline SVG charts (sparkline, line, stacked bars), KPI tiles, the reason form for writes |
| `src/pages/` | One file per page, with its test next to it |
| `src/api/` | `client.ts` (typed `openapi-fetch` client), `schema.gen.ts` (generated), one module per area (`admin.ts`, `auth.ts`, `health.ts`, `ops.ts` for Overview and Operations) |
| `src/mocks/` | MSW handlers for tests and `VITE_API_MOCKS=all`. Only tests and `main.tsx` may import them. |
| `src/styles.css` | All styles. Colors are tokens on `:root`, with a dark set for `prefers-color-scheme` and `html[data-theme]`. |

## API types

The typed client is generated from `apps/web/openapi.json`, the same file the web app uses, so
there is one OpenAPI document to keep fresh (`apps/api/tests/test_openapi_fresh.py` checks it).
After an API change:

```powershell
uv run python apps/web/scripts/export_openapi.py
pnpm --dir apps/web gen:api
pnpm --dir apps/admin gen:api
```

`src/api/schema.test.ts` fails when `src/api/schema.gen.ts` is stale.

## Sign-in

The admin app has its own sign-in and sessions (AA-1 to AA-4, `strong_api.admin.auth`): email and
password (the admin's account password, with a confirmed email), an email link, or Google, all
under `/api/admin/auth`. Only active rows in `admin_users` get a session. The session is a row in
`admin_sessions` and the host-only `sh_admin` cookie (HttpOnly, SameSite=Strict, Secure outside
local); it ends after 2 h without use or 12 h after sign-in. The candidate `sh_session` never opens
the admin app. Email links land on `/signin/verify`, which posts the token to the API.

`GET /api/admin/me` answers 401 without an admin session, and the Shell then shows sign-in.
Settings > Admins manages who is an admin; Settings > My sessions lists and revokes sessions.

In mock mode (`VITE_API_MOCKS=all`) sign in as admin@example.com with `admin-password`.
