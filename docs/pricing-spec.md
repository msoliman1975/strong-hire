# Strong Hire Pricing, Billing and Retention: Product & Technical Spec v0.1 (draft)

Status: draft, 2026-10-30. Decisions PD-1 to PD-14 below.
This spec replaces the "Suggested plan" in `docs/spec.md` (Pricing and cost model) and redefines
BL-1 and BL-2 for the December 2026 launch, which now ships v2 (interview plus coach). It builds on
the launch contracts already merged in migration 0018 (`plan_code`, `price_variant`,
`allowance_start`, top-up grants, `email_logs`) and on the admin spec (`docs/admin-spec.md`: AO-3,
AU-2 to AU-6, OC-3, AL-1).

## Overview

Strong Hire sells one paid plan, with two ways to pay. The goals, in order:

1. **Adoption:** a free tier that shows both halves of the product (a debrief and a coached story),
   a price below "serious prep" competitors, a founding-member price, and a refund guarantee.
2. **Profitability:** a shared minute pool so no plan is unlimited on voice, at least 75% gross
   margin at the cap on every plan, and live unit economics in the admin portal.
3. **Plan simplicity:** one product, one plan, monthly or 90 days. No tiers, no annual price, and
   no top-ups at launch.

### The offer

| | **Free** | **Strong Hire** |
| --- | --- | --- |
| Price | $0 | **$39 a month**, or **$89 for 90 days** (one payment, no auto-renew). CAD $52 and CAD $119 |
| Interviews | 1 interview, up to 30 minutes, with its debrief | A shared pool of **500 minutes per 30 days** for interviews and voice coaching, shown as "about N interviews" |
| Coach | Text coaching for **2 stories** | Text coaching with no limit (fair use, GR-5); voice coaching uses the pool |
| Plan page, gap analysis, readiness | Yes, rate limited | Yes, rate limited |
| Story library, debriefs, transcripts | Kept until the user deletes them | Kept until the user deletes them |
| Founding price | | **$29 a month for 12 months** for the first 500 monthly subscribers, or until 2027-03-31 |
| Guarantee | | First payment refunded on request within 7 days (PB-14) |

### Unit economics

The planning numbers. The admin portal computes the same table from real data (AB-3).

| Plan | Revenue | AI cost (typical / cap) | Stripe fee | Margin |
| --- | --- | --- | --- | --- |
| Monthly | $39 | $3.25 / $6.50 | $1.43 | 88% / 80% |
| 90-day pass | $89 | $10 / $19.50 | $2.88 | 85% / 75% |
| Founding price | $29 | $3.25 / $6.50 | $1.14 | 85% / 74% |
| Free user | $0 | ~$0.70 (1 interview plus text coaching) | – | Paid back by about 1 in 50 converting |

Assumptions:

- AI cost is about **$0.013 per session minute** (the spec's $0.60 per 45-minute session). The
  `claude` profile measures lower; the admin portal replaces the estimate with measured cost.
- Typical use is 250 minutes per 30 days (half the pool). The cap is the full 500.
- Stripe fee is 2.9% + $0.30 (US cards). Canadian and international cards add 1.5% and currency
  conversion adds 1%, so CAD payments cost about $0.60 to $1.00 more each.
- The free user: one 30-minute interview (~$0.40), two coached stories by text (~$0.15), gap
  analysis and plan page (~$0.15). $0.70 × 50 is about one month's contribution of a monthly
  subscriber ($39 − $3.25 − $1.43 = $34.32).
- Fixed costs (~$120 a month, `docs/spec.md`) are covered by about 4 subscribers.

### Decisions

| ID | Decision |
| --- | --- |
| PD-1 | One product, one paid plan, two billing options: monthly subscription and a 90-day pass. No tiers and no annual price. |
| PD-2 | Monthly is $39 (CAD $52). The 90-day pass is $89 (CAD $119). Prices are set in config, never in code. |
| PD-3 | Interviews and voice coaching share one pool of 500 minutes per 30-day allowance. Text coaching does not use the pool. |
| PD-4 | Free tier: one interview of up to 30 minutes (any type, including Custom), two stories built with the text coach, and the plan page. This replaces the two 10-minute mini interviews. |
| PD-5 | The 90-day pass is a one-time Stripe Checkout payment (`mode=payment`). It does not renew. Its pool resets every 30 days (`allowance_start`), so it gives 3 × 500 minutes. It reuses `plan_code = job_hunt_3m`; the UI calls it "90-day pass". |
| PD-6 | Founding price: a Stripe coupon of $10 off the monthly price for 12 months, applied automatically at Checkout, with `max_redemptions = 500` and `redeem_by = 2027-03-31`. Users never type a code. It does not apply to the pass. |
| PD-7 | Top-ups (contract L01, `GrantKind.TOP_UP`) stay built but are off at launch (`BILLING_TOPUPS_ENABLED=false`). Turn them on only if more than 10% of subscribers hit the cap in a month (AB-5). |
| PD-8 | The 7-day guarantee is self-serve and automatic when its conditions hold (PB-14). This amends admin D-7 for this one case; every other refund stays in the Stripe dashboard. |
| PD-9 | Pause instead of cancel: monthly subscribers can pause for 1, 2 or 3 months, at most 3 months in any 12 (RT-1). Passes cannot pause. |
| PD-10 | A paid user who leaves becomes an **alumnus**: the free plan, with the story library, debriefs and plans kept, and one-click resubscribe (RT-4). |
| PD-11 | Price test: after week 4 of launch, new paywall visitors are split between $39 and $49 monthly (`price_variant` p39, p49). Founding-price users are never in the test. Decision rule in AB-6. |
| PD-12 | Taxes: Stripe Tax computes sales tax, GST/HST and QST at Checkout. US prices are shown before tax; Canadian prices are shown with "plus applicable taxes". Confirm with an accountant before live mode (OQ-1). |
| PD-13 | Only one paid access is active at a time. Buying is refused while a paid plan is active, except the two switches in PB-9 and PB-10. |
| PD-14 | Billing text in the product talks about interviews, not minutes: "About 6 interviews left (270 min)". Minutes stay the unit of metering. |

### Non-goals (launch)

- Annual billing, team or seat plans, B2B invoicing (later, `docs/spec.md` Scope).
- Discount codes typed by users, student pricing, regional pricing outside the US and Canada.
- Rollover of unused minutes.
- Refunds from the admin app (D-7 stays, apart from PB-14).
- Ads or a free tier paid for by ads.

## Plans and entitlements (PB)

These replace BL-1 and BL-2. Priority: P0 must ship at launch, P1 ships if time allows.

| ID | Requirement | Priority |
| --- | --- | --- |
| PB-1 | `GET /billing/plan` returns the offer from config: plan name; monthly and pass prices in the user's currency; pool minutes per allowance; allowance length (30 days); pass length (90 days); free interview count and maximum length; free coached stories; founding offer (active, price, months, spots left); guarantee days; `billing_enabled`. The web app shows only these values and never hard-codes a price. | P0 |
| PB-2 | **Free tier:** `BILLING_FREE_INTERVIEWS` (default 1) interviews for the life of the account, each up to `BILLING_FREE_MAX_MIN` (default 30). A free account that asks for a longer session gets HTTP 402 `full_interview_requires_plan`. A session counts once it has started and did not fail (as today). Gap analysis and the plan page are free and rate limited. | P0 |
| PB-3 | **Free coach:** a free account can create `BILLING_FREE_COACH_STORIES` (default 2) stories with the text coach. Creating the next one returns HTTP 402 `coach_requires_plan`. Editing existing stories with the coach stays allowed, within GR-5 limits. Voice coaching needs the paid plan (`voice_coach_requires_plan`). | P0 |
| PB-4 | **Paid access** is: a monthly subscription in Stripe status `active` or `trialing`; or `past_due` within the 7-day grace (RT-8); or a pass with `now < period_end`; or an active comp grant (AU-5). Paused subscriptions (RT-1) are not paid access. | P0 |
| PB-5 | **One pool:** a paid user has `BILLING_POOL_MINUTES` (default 500) per allowance. Interview sessions and voice coach sessions both bill whole minutes into `subscriptions.minutes_used`. Text coach sessions record minutes for analytics but never bill the pool. Support grants (AU-3) add to the pool as today. | P0 |
| PB-6 | **Allowance periods:** for monthly plans the allowance is the Stripe billing period, and a new period resets `minutes_used` (as today). For passes the allowance is 30 days from `allowance_start`. When an entitlement is read on or after `allowance_start + 30 days`, it moves `allowance_start` forward by whole 30-day steps and sets `minutes_used` to 0 in the same transaction. No cron is needed. | P0 |
| PB-7 | **Starting a session:** interviews and voice coach sessions may start while at least 1 minute is left. `max_minutes = min(chosen length, minutes left)`, so the session timer stops when the pool runs out. When the pool is empty the code is `minutes_exhausted`; the message gives the reset date. A voice coach session in progress that hits 0 gets a one-minute warning and then ends cleanly, saving the story. | P0 |
| PB-8 | **Display:** `GET /billing/usage` adds `interviews_left_estimate = floor(minutes_left / 45)`, `minutes_by_kind` (interview, voice coach) for the current allowance, `allowance_resets_at`, `plan_code`, `pass_ends_at`, `founding` and `paused_until`. The meter reads "About 6 interviews left · 270 min · resets Nov 30" (PD-14). | P0 |
| PB-9 | **Monthly to pass:** a monthly subscriber can buy the pass at any time (for example from the cancel flow, RT-2). On payment the pass starts at once; the monthly subscription is canceled now, and the unused part of the current period is refunded pro rata to the original charge. Minutes used this period carry over into the pass's first allowance. | P1 |
| PB-10 | **Pass to monthly:** in the last 7 days of a pass, the user can start a monthly subscription that first charges when the pass ends (Stripe `trial_end = pass period_end`). Until then the pass rules apply. | P1 |
| PB-11 | **Resubscribe:** a canceled or alumni user can buy either option again from the paywall or Account. Their library, plans and debriefs are still there (RT-4). | P0 |
| PB-12 | **Founding price:** while the founding offer is active (PD-6), monthly Checkout attaches the founding coupon. The paywall shows the founding price, the regular price struck through, "for 12 months", and spots left when fewer than 100 remain. After 12 months the subscription renews at the regular price; an email 14 days before says so (RT-6). | P0 |
| PB-13 | **Price test:** each new free account gets a `price_variant` when it first sees the paywall, stored on the user and copied to the subscription. A variant fixes the monthly price shown and charged. Variants and their weights come from config (`BILLING_PRICE_TEST`, empty = no test). Founding users are always `founding`. | P1 |
| PB-14 | **7-day guarantee:** Account shows "Request a refund" when this is the user's first paid charge ever, it is less than 7 days old, and fewer than 90 pool minutes are used. One click asks one question (what fell short), refunds the charge through the Stripe API, ends paid access at once, and writes an `audit_logs` row (`billing.guarantee_refund`). Outside these conditions the button is not shown and the help text points to support. | P0 |
| PB-15 | Every 402 body keeps the shape `{code, message, upgrade_url}`. New codes: `coach_requires_plan`, `voice_coach_requires_plan`, `plan_paused`. | P0 |

## Stripe integration (SB)

| ID | Requirement | Priority |
| --- | --- | --- |
| SB-1 | **Catalog:** one product, "Strong Hire". Prices: `monthly` (recurring monthly, USD 3900 with a CAD 5200 currency option) and `pass_90d` (one-time, USD 8900 with a CAD 11900 currency option), plus one monthly price per price-test arm (for example `monthly_p49`). Prices are found by Stripe `lookup_key`, not by id in env. Coupon `founding` (amount off USD 1000 / CAD 1300, duration repeating 12 months, `max_redemptions` 500, `redeem_by` 2027-03-31). | P0 |
| SB-2 | `scripts/stripe-setup.ps1` creates or updates the catalog in test mode from config, idempotently by lookup key, and prints what it changed. It refuses live keys unless `-Live` is passed and `STRIPE_ALLOW_LIVE=true`. | P0 |
| SB-3 | At start the API looks up each configured lookup key once and checks that the Stripe amount equals the config price. A mismatch logs an error and makes `GET /billing/plan` report `billing_enabled=false`, so nobody is charged a price the app does not show. | P0 |
| SB-4 | `POST /billing/checkout` takes `{"option": "monthly" | "pass_90d"}`. Monthly uses `mode=subscription` with the price for the user's variant and the founding coupon when it applies. The pass uses `mode=payment`. Both set `client_reference_id`, `customer`, `automatic_tax`, `customer_update.address=auto`, `allow_promotion_codes=false`, and metadata `plan_code`, `price_variant`, `founding`. Currency follows the customer's country (Stripe adaptive currency, USD or CAD only). | P0 |
| SB-5 | **Webhooks**, in addition to today's events: `checkout.session.completed` with `mode=payment` creates or updates the user's subscription row as a pass (`plan_code=job_hunt_3m`, status active, `period_start` = paid at, `period_end` = paid at + 90 days, `allowance_start` = paid at, `minutes_used` = 0, `stripe_price_id`, no subscription id). `invoice.payment_failed` starts the grace (RT-8). `charge.refunded` keeps its AU-6 audit row and, for a pass charge refunded in full, ends the pass. Each event is still applied once (stripe_events). | P0 |
| SB-6 | **Pause:** the app pauses a subscription with Stripe `pause_collection` (`behavior=void`, `resumes_at`). The webhook stores `paused_until` and the new status `paused` when `pause_collection` is set, and clears them when it is removed. The current mapping of Stripe `paused` to canceled stays for trial-end pauses. | P0 |
| SB-7 | **Customer Portal** configuration: update payment method, see invoices, cancel at period end. Plan switching and pausing are off in the portal; the app owns them (RT-1, PB-9, PB-10). The cancel flow in the app (RT-2) runs before the portal's cancel step. | P0 |
| SB-8 | A daily worker job ends passes whose `period_end` has passed (status canceled, `orgs.plan = free`) and sends the emails in RT-6. Entitlements do not wait for it (PB-4 checks `period_end`). | P0 |
| SB-9 | Test mode until launch, as today. The billing README gets a Stripe CLI walk-through for each new flow: pass purchase, allowance reset inside a pass, founding coupon, pause and resume, guarantee refund, payment failure and grace. | P0 |
| SB-10 | Tests use Stripe-format fixtures and `FakeStripe`, never the network. Each SB and PB requirement has at least one test. | P0 |

## Guardrails (GR)

Guardrails protect margin and stop abuse without getting in the way of honest users.

| ID | Requirement | Priority |
| --- | --- | --- |
| GR-1 | **One live session per account:** a second interview or voice coach session cannot start while one is in progress (HTTP 409 `session_in_progress`). This stops account sharing from multiplying cost. | P0 |
| GR-2 | **Daily voice cap per user:** at most `BILLING_DAILY_VOICE_MIN` (default 180) minutes of interviews plus voice coaching per UTC day, on any plan (`daily_limit_reached`). | P0 |
| GR-3 | **Free tier, one per person:** the free interview needs a verified email. Emails are normalized before the check (lower case; for Gmail, dots and `+tag` removed) and stored as `users.email_normalized`; a normalized email that already used a free interview, on a deleted account too, gets none (a salted hash is kept after deletion). Disposable email domains get the gap analysis and plan page but no free interview. | P0 |
| GR-4 | **Free tier, per network:** at most `FREE_INTERVIEWS_PER_IP_30D` (default 3) free interviews per IP address (stored as a salted hash, 30-day retention) in 30 days. Over the limit the account keeps the free tools, and the paywall says the free interview is not available on this network. | P1 |
| GR-5 | **Text coach fair use:** at most 60 coach turns per hour and 300 per day per user. Over the limit: "Strova needs a short break", with the time it comes back. Admin can change the limits as runtime settings. | P0 |
| GR-6 | **Guarantee, once per person:** PB-14 is refused when the normalized email or the card fingerprint (from the Stripe payment method) already had a guarantee refund. | P0 |
| GR-7 | **Spend cap:** the daily spend cap (OC-3) stays. At launch its default becomes `max($25, $1.00 × active paid users ÷ 10)` per day, so it grows with revenue; an admin can still set a fixed value. | P0 |
| GR-8 | **Kill switches**, as runtime settings in Controls (OC): pause free interviews (paid users unaffected), pause the founding offer, pause guarantee refunds (the button says to contact support), pause the price test. Each change needs a reason and is audited (AA-6). | P0 |
| GR-9 | **Cost watch per user:** a user whose model cost in the current allowance passes $10 is flagged on the Revenue page (AB-7) and in the user detail. Nothing is blocked automatically. | P0 |
| GR-10 | **Price integrity:** a test checks that no price, minute cap or coupon amount appears in code outside `strong_api.billing.settings` and config files, the same way the model-name test works. | P1 |

## Admin portal: revenue and unit economics (AB)

A new **Revenue** page in `apps/admin`, next to Overview. It uses the AO ranges (24 h, 7, 30, 90
days, compared with the previous period) and the AO-8 rule: what cannot be measured yet shows "not
measured" with the reason.

| ID | Requirement | Priority |
| --- | --- | --- |
| AB-1 | **Headline:** MRR (monthly subscriptions at their current price, plus pass revenue ÷ 3 for active passes), cash collected, active paid users by option (monthly, founding, pass, comp), paused, new paid, cancellations, refunds (count, amount, guarantee share), ARPPU. | P0 |
| AB-2 | **Founding offer:** spots used and left, redeem-by date, founding share of paid users, and the date each founding cohort reaches its renewal at the regular price. | P0 |
| AB-3 | **Unit economics table:** the table in this spec, filled from real data for the range. One row per option (monthly, 90-day pass, founding, each price-test arm) with users, revenue per allowance, AI cost per paid user (median and p95, from `usage_events` including coach and gap analysis), Stripe fee (actual from the balance transaction when stored, otherwise the 2.9% + $0.30 estimate, marked as such), and gross margin (median and p95). The free row shows AI cost per free user, free-to-paid conversion within 14 days, and "paid back by 1 in N" with N = (first allowance contribution) ÷ (cost per free user). The cell turns red when margin at p95 falls below 75%, or when real conversion is below 1 in N. | P0 |
| AB-4 | **Cost per minute:** AI cost per billed minute over time, for interviews, voice coaching and text coaching, against the $0.013 planning figure. | P0 |
| AB-5 | **Pool use:** distribution of the share of the pool used per paid user per allowance (0–25%, 25–50%, 50–75%, 75–100%, at the cap), the share at the cap (the PD-7 top-up trigger is 10%), and the minute split between interviews and voice coaching. | P0 |
| AB-6 | **Price test:** per arm: paywall views, checkouts started, paid, conversion, revenue per paywall view, 30-day churn, with sample sizes. The page names a winner only after 300 paywall views and 30 paid users per arm: pick $49 if its conversion is at least 80% of the $39 arm and its churn is no higher; otherwise $39. | P1 |
| AB-7 | **Watch list:** the users flagged by GR-9 (cost, minutes, sessions), accounts and networks blocked by GR-3 and GR-4, and refused guarantee requests (GR-6). Each row links to the user detail. | P0 |
| AB-8 | **Retention:** monthly churn of monthly subscribers (target under 10%), pass renewal rate (pass to monthly or a second pass), pauses started and the share that resumed, alumni and the share that came back within 90 and 365 days, exit survey breakdown (reasons, and "got the job" share), offers reported (RT-5), and a cohort table by first paid month (share still paid at months 1, 2, 3, 6). | P0 |
| AB-9 | **User detail (AU-2) gains:** plan option, price variant, founding flag and its end date, pass end, pause status, pool split this allowance, lifetime revenue, lifetime AI cost, lifetime margin, guarantee eligibility, and referral counts. New action: **extend pass** by N days (a `comp_plan` grant until the new date, with a reason). | P0 |
| AB-10 | **Alerts** (AL-1 rules, seeded and editable): cost per billed minute above $0.020 over 7 days (warning); p95 cost per paid user above $10 in an allowance (warning); founding spots under 50 (warning); guarantee refunds above 8% of new paid users in 7 days (warning); webhook errors or a pass not ended by SB-8 (critical); daily free interviews above 3 times the 7-day average (warning, abuse). | P0 |

## Retention (RT)

Interview prep is episodic, so retention means three things: keep people through one search, keep
them reachable for the next one, and turn their success into referrals.

| ID | Requirement | Priority |
| --- | --- | --- |
| RT-1 | **Pause:** Account and the cancel flow offer "Pause for 1, 2 or 3 months". During a pause nothing is charged, no new interview or voice coach session can start (`plan_paused`), and everything else stays readable: library, plan page, debriefs, readiness. Text coaching works for existing stories only. "Resume now" works at any time and starts a new allowance. At most 3 paused months in any 12. | P0 |
| RT-2 | **Cancel flow** (before the Stripe portal): (1) the exit survey (exists); (2) if "I got the job", go to RT-5; (3) if the reason is price, offer the 90-day pass ("$30 a month, paid once") on monthly plans; (4) otherwise offer a pause; (5) then cancel at period end. Each step can be skipped in one click. The flow never hides the cancel button. | P0 |
| RT-3 | **During the search:** the weekly plan and reminders (UX spec PS-4, PS-6), the interview date countdown emails (L06 kinds), and a "minutes low" email at 20% of the pool left (L06 `minutes_low`) are the paid-period engagement loop. Strova's next step on Home includes "rehearse again" when readiness is low and minutes are left. | P0 |
| RT-4 | **Alumni:** when paid access ends, the user moves to the free plan with all content kept, a "Welcome back" Home that starts with their last role and stories, and a one-click resubscribe with the last option they used selected. Alumni do not get another free interview. | P0 |
| RT-5 | **"I got the offer":** a button on the role page and in the cancel flow. It records the offer on the target role (`stage = offer`, with the date), shows a short congratulations, asks for an optional testimonial with explicit consent to publish, shows the referral link, and explains that cancelling keeps everything (alumni). Feeds the "offer reported" metric. | P0 |
| RT-6 | **Lifecycle emails** (new `email_kind` values): `pass_ending_7` and `pass_ending_1` (offer PB-10), `pause_resuming_3` (3 days before a pause ends), `founding_renewal_14` (14 days before the founding price ends), `referral_reward`. Product emails respect `product_email`; win-back emails (`winback`, at 30 and 90 days after access ends, not sent after an offer was reported) need `marketing_email` consent (CASL). One email per kind and reference (`email_logs`). | P0 |
| RT-7 | **Referrals:** every user has a referral link. A new account from the link gets one extra free interview. When that account finishes its first interview, the referrer gets 45 pool minutes (paid) or one free interview (free), as a `minute_grants` row with reason `referral`. At most 10 rewards per referrer per year. No reward for the same normalized email, card fingerprint or IP hash (GR-3, GR-4). | P1 |
| RT-8 | **Failed payments:** on `invoice.payment_failed` the user keeps paid access for 7 days, sees a banner with "Update card" (portal), and Stripe sends its own retry emails (Smart Retries on). After 7 days without payment, access stops until Stripe reports the invoice paid. | P0 |
| RT-9 | **Targets** (hypotheses, reviewed after 8 weeks): monthly churn under 10%; 50% of pauses resume; 15% of alumni come back within 12 months; guarantee refunds under 5% of new paid users; 20% of paid users send at least one referral. | P0 |

## App changes (candidate web app)

Screens follow `docs/ux-strova/ux-spec.md`. Billing pages stay where they are (Paywall at
`/upgrade`, Account), as the UX spec says.

| ID | Requirement | Priority |
| --- | --- | --- |
| PW-1 | **Paywall:** one card with a Monthly / 90-day pass switch (Monthly first), what is included, the price (founding price and struck-through regular price when it applies), the guarantee line, and one comparison line ("A single human mock interview costs $179 or more"). Opened from a 402, from the free debrief, and from Strova's suggestions. | P0 |
| PW-2 | **After the free debrief:** the debrief ends with the hire signal, the next plan item, and one call to action to subscribe; the free coached stories are offered first if unused. | P0 |
| PW-3 | **Usage meter** in the shell and on Account, in the PB-8 wording. At 0 minutes it shows the reset date, and the pass end date for passes. | P0 |
| PW-4 | **Account, Plan section:** option and price, next charge or pass end, founding end date, pool split, Pause / Resume, Cancel (RT-2), Request a refund (PB-14, when eligible), Update card (portal), invoices (portal). | P0 |
| PW-5 | All new billing copy is plain English, short sentences, US and Canadian spelling neutral, and lists prices with currency (USD or CAD). | P0 |

## Data model changes

Per `CLAUDE.md`, these go first in one small `packages/core` PR with one migration, schemas
regenerated, and a working `downgrade()`.

| Change | Notes |
| --- | --- |
| `SubscriptionStatus` gains `paused` | RT-1, SB-6 |
| `subscriptions` gains `paused_until`, `founding` (bool), `currency` (`usd`, `cad`), `grace_until`, `refunded_at` | PB-12, RT-1, RT-8, PB-14 |
| `users` gains `email_normalized` (indexed), `price_variant`, `referred_by_user_id`, `referral_code` (unique) | GR-3, PB-13, RT-7 |
| New table `free_tier_claims` (normalized email hash, IP hash, claimed_at). Not user-owned (kept after account deletion, holds hashes only); 30-day retention for IP hashes | GR-3, GR-4. Add to the privacy notice |
| New table `paywall_views` (org_id, user_id, price_variant, source, at), user-owned, add to `USER_OWNED_TABLES` | AB-6; server-side because analytics consent is off by default |
| New table `referrals` (org_id, referrer_user_id, referee_user_id, status, rewarded_at), user-owned | RT-7 |
| `coach_sessions.minutes_billed` | PB-5: voice coach minutes billed to the pool, like `interview_sessions.minutes_billed` |
| `EmailKind` gains `pass_ending_7`, `pass_ending_1`, `pause_resuming_3`, `founding_renewal_14`, `referral_reward` | RT-6 |
| `minute_grants.reason` value `referral` (free text today, no migration if it stays free text) | RT-7 |

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `BILLING_PRICE_MONTHLY_USD`, `BILLING_PRICE_MONTHLY_CAD` | `39`, `52` | Shown on the paywall; SB-3 checks Stripe matches |
| `BILLING_PRICE_PASS_USD`, `BILLING_PRICE_PASS_CAD` | `89`, `119` | |
| `STRIPE_LOOKUP_MONTHLY`, `STRIPE_LOOKUP_PASS` | `monthly`, `pass_90d` | Replace `STRIPE_PRICE_ID` |
| `BILLING_POOL_MINUTES` | `500` | Replaces `BILLING_MINUTES_CAP` |
| `BILLING_PASS_DAYS`, `BILLING_ALLOWANCE_DAYS` | `90`, `30` | |
| `BILLING_FREE_INTERVIEWS`, `BILLING_FREE_MAX_MIN` | `1`, `30` | Was 2 mini interviews |
| `BILLING_FREE_COACH_STORIES` | `2` | |
| `BILLING_FOUNDING_COUPON` | `founding` | Empty turns the offer off |
| `BILLING_GUARANTEE_DAYS`, `BILLING_GUARANTEE_MAX_MIN` | `7`, `90` | |
| `BILLING_PRICE_TEST` | empty | For example `p39:50,p49:50` |
| `BILLING_TOPUPS_ENABLED` | `false` | PD-7 |
| `BILLING_DAILY_VOICE_MIN` | `180` | GR-2 |
| `FREE_INTERVIEWS_PER_IP_30D` | `3` | GR-4 |

## Build plan

Each step is one PR into `main` with green CI. Steps 2 to 5 can run in parallel after step 1.

| Step | Scope | Owner | IDs |
| --- | --- | --- | --- |
| 1 | Core contracts: enums, columns, tables, migration, schemas | Shared (`packages/core`) | Data model |
| 2 | Billing API: offer, entitlements (pool, pass, allowance reset, free tier, coach metering), Checkout both modes, webhooks, pause, guarantee, switches; Stripe setup script and README | API (`apps/api/.../billing`, `coach`, `sessions`), `scripts/` | PB, SB, GR-1 to GR-6, RT-1, RT-8 |
| 3 | Web: paywall, meter, Account plan section, cancel flow, offer flow, referral link | Web (`apps/web`) | PW, RT-2, RT-4, RT-5, RT-7 |
| 4 | Worker: pass ending job, lifecycle emails, referral rewards, alert metrics | Worker (`apps/worker`) | SB-8, RT-6, RT-7, AB-10 |
| 5 | Admin: Revenue page, user detail fields, extend pass, Controls switches, alert rules | Admin (`apps/admin`, `apps/api/.../admin`) | AB, GR-7 to GR-9 |
| 6 | Launch check in Stripe test mode: every README walk-through passes; then live keys | P12 | SB-9 |

## Open questions

- [ ] OQ-1: Tax display and registration for Canada (GST/HST, Quebec QST) and US states. Accountant before live mode.
- [ ] OQ-2: CAD prices: $52 and $119 follow the exchange rate; $49 and $109 may convert better.
- [ ] OQ-3: Founding cap: 500 spots or the date, whichever comes first, is assumed.
- [ ] OQ-4: Quebec consumer protection rules for prepaid passes and automatic renewal of the founding price (notice periods). Lawyer, together with Appendix A.
- [ ] OQ-5: Whether alumni keep text coaching on existing stories (cheap, good for return rate) or read-only access only.
