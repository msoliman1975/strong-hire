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
| `src/pages/` | One file per page, with its test next to it |
| `src/api/` | `client.ts` (typed `openapi-fetch` client), `schema.gen.ts` (generated), one module per area (`admin.ts`, `auth.ts`, `health.ts`) |
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

For now the admin app uses the candidate sign-in routes, served on the admin host under `/api`,
so the host-only `sh_session` cookie belongs to the admin host. The API's `is_admin` flag
(`ADMIN_EMAILS`) decides who gets in; everyone else sees "Page not found" and a sign-out button.
Email links and Google sign-in pass `app=admin`, so they come back to `ADMIN_BASE_URL`. A later
PR replaces this with dedicated admin sessions (AA-1 to AA-3).
