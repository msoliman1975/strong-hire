# Strong Hire marketing site (L04)

The public site for getstronghire.com: home, how it works, pricing, sample debrief, waitlist,
interview guides and legal pages. Astro, static output, served by Caddy on the apex domain. The
app lives on `app.getstronghire.com`.

```powershell
pnpm --dir apps/site install
pnpm --dir apps/site dev      # http://localhost:4321
pnpm --dir apps/site build    # dist/
```

## Theme

`src/styles/site.css` copies the tokens of theme "The Approved h" from `apps/web/src/styles.css`
(colors, fonts, radius, spacing) and the app's header, buttons, tags, score bars and hire-signal
ladder. Change the app first, then copy the change here. The logo in `src/components/BrandMark.astro`
is the same drawing as `apps/web/src/components/BrandMark.tsx`. Color rules: amber means practice
and is a fill only, green means an earned verdict and is never on a button or link, ink means action.

The screenshots in `public/shots/` come from the app running with `VITE_API_MOCKS=all` (example data,
company renamed to "Northwind Pay"). Retake them when the app's look changes.

## Switches (`src/site.config.ts`)

| Setting | Today | Change when |
| --- | --- | --- |
| `CTA_MODE` (or `PUBLIC_CTA_MODE=signup` at build) | `waitlist` | Sign-ups open on Dec 14: buttons become "Start free" and go to the app |
| `SHOW_COMPANY_NAMES` | `true` | The lawyer says no to plain-text names: every page says "21 major tech companies" |
| `LEGAL_DRAFT` | `true` | The lawyer's texts replace the drafts in `src/pages/legal/` |
| `PUBLIC_APP_URL` | `https://app.getstronghire.com` | Never, unless the app moves again |

## Rules for copy

- Company names only as plain text, always next to the not-affiliated notice. No logos, brand
  colors, or "official", "partner", "real Google interview". No company names in headlines.
- A hire signal is a practice estimate, never a prediction of a company's decision.
- Prices stay hidden until launch (`/pricing` shows the minutes clause only).

## Waitlist

The form posts to `/api/public/waitlist` (PR #117). On the apex, Caddy proxies only `/api/public/*`
to the API. The confirmation link in the email points at the app (`WEB_BASE_URL`).

## Guides (Q13)

`src/pages/guides/[company]/[role].astro` builds one page per company profile in `/profiles` whose
`meta.status` is `published`, for each role in its loop. None are published yet, so no guide pages
are built and the Guides menu item stays hidden.

## Checks

CI builds the site and runs Lighthouse (`lighthouserc.json`): performance and best practices 90+,
accessibility and SEO 95+. The apex sends a strict CSP (`default-src 'self'`), so pages must not use
inline scripts or `style` attributes.
