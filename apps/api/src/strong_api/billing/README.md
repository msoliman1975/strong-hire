# Billing and account (P9)

Requirement IDs: BL-1, BL-2 (billing), AC-1, AC-2 (account). Stripe runs in test mode until launch.
The API refuses live keys (`sk_live_`) unless `STRIPE_ALLOW_LIVE=true`.

## What the code does

| Endpoint | What it does |
| --- | --- |
| `GET /billing/plan` | Plan name, price, minute cap, free interviews. All from env (`BILLING_*`). |
| `GET /billing/usage` | Usage meter: plan, minutes used and left, period end, free interviews left, and why a new session is blocked. |
| `POST /billing/checkout` | Creates the Stripe customer (once) and returns a Checkout URL. |
| `POST /billing/portal` | Returns a Customer Portal URL. `{"flow": "cancel"}` opens the cancel step. |
| `POST /billing/exit-survey` | Saves the 2 cancellation questions: why leaving, did you get the job. |
| `POST /billing/webhook` | Stripe events. Checks the signature, applies each event id once. |
| `POST /billing/dev/usage` | Only when `APP_ENV=local`: uses plan minutes without a voice session. |
| `PUT /account/consent` | AC-2 consent. Each change is written to AuditLog. |
| `POST /account/export` | AC-1 export, as a worker job. `GET /account/export/{id}` gives the status. |
| `GET /account/export/{id}/download` | The zip (data.json plus original resume files). Works once. |
| `DELETE /account` | AC-1 delete: cancels Stripe, deletes all rows now, files by a worker job. |

Webhook events handled: `checkout.session.completed`, `customer.subscription.created`,
`customer.subscription.updated`, `customer.subscription.deleted`, `customer.subscription.paused`,
`customer.subscription.resumed`, `invoice.paid`. Other events are stored and ignored.

Rules:

- Free plan: `BILLING_FREE_INTERVIEWS` interviews (default 1) for the life of the account. A
  session counts once it has started and did not fail. Gap analyses are free. Their rate limit
  is in `strong_api.gap` (P6, `GAP_RATE_LIMIT_PER_HOUR` and `GAP_RATE_LIMIT_PER_DAY`).
- Paid plan (Stripe status `active` or `trialing`): `BILLING_MINUTES_CAP` minutes per period
  (default 300). A session can start while 1 or more minutes are left. `max_minutes` tells the
  session timer where to stop.
- A new period start from Stripe sets `minutes_used` to 0.
- A canceled subscription stays canceled, and events about an older period are ignored.

### For the session routes (P7, P10)

```python
from strong_api.billing import ensure_can_start_session, record_session_minutes

# POST /sessions
ent = await ensure_can_start_session(db, user.org_id)  # HTTP 402, detail.code is
max_minutes = ent.max_minutes(config.duration_min)  # upgrade_required or minutes_exhausted

# when a session ends (safe to call again; it bills only the difference)
await record_session_minutes(db, session)
await db.commit()
```

## Environment variables

| Variable | Example | Notes |
| --- | --- | --- |
| `STRIPE_SECRET_KEY` | `sk_test_...` | Stripe dashboard, test mode, Developers, API keys. |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` | Printed by `stripe listen`. A deployed endpoint has its own. |
| `STRIPE_PRICE_ID` | `price_...` | The monthly price of the plan. |
| `BILLING_PRICE_USD_MONTH` | `29` | Shown on the paywall. Keep it equal to the Stripe price. |
| `BILLING_MINUTES_CAP` | `300` | Minutes per billing period. |
| `BILLING_FREE_INTERVIEWS` | `1` | Free interviews per account. |
| `ACCOUNT_EXPORT_TTL_S`, `ACCOUNT_EXPORT_MAX_MB` | `86400`, `100` | Export download window and size limit. |

With no Stripe keys, the app still runs: the paywall says payments are not set up, and checkout
and the portal answer HTTP 503.

## Check the full flow locally with the Stripe CLI

These steps need a Stripe account in test mode. They were not run yet: no Stripe account existed
when P9 was built. The automated tests use Stripe-format fixtures instead.

### 1. One-time Stripe setup (test mode)

Install the Stripe CLI (`winget install Stripe.StripeCli`), then in PowerShell:

```powershell
stripe login
stripe products create -d name="Strong Hire monthly"
# Use the prod_... id from the output:
stripe prices create -d product=prod_XXXX -d unit_amount=2900 -d currency=usd -d "recurring[interval]=month"
```

In the Stripe dashboard (test mode), open Settings, Billing, Customer portal. Turn on
"Cancel subscriptions" with "At the end of the billing period", and save.

### 2. Keys and webhook forwarding

Put these in `.env` (never commit it):

```text
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PRICE_ID=price_...
```

In a second PowerShell window, forward events to the API (port 8700) and leave it running:

```powershell
stripe listen --forward-to localhost:8700/billing/webhook --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,invoice.paid
```

Copy the `whsec_...` it prints into `.env` as `STRIPE_WEBHOOK_SECRET`. Then start the stack:

```powershell
./scripts/dev.ps1 up
```

### 3. Subscribe

1. Open http://localhost:5180, use the dev login, and finish sign-up.
2. The usage meter says "Free plan: 1 free interview left".
3. Open http://localhost:5180/upgrade and select Subscribe. Stripe Checkout opens.
4. Pay with card `4242 4242 4242 4242`, any future date, any CVC, any postal code.
5. You return to the dashboard. The meter says "0 of 300 minutes used".
6. The `stripe listen` window shows `[200]` for each event.

Check the row:

```powershell
docker compose -f infra/compose.yaml --env-file .env exec postgres psql -U strong -c "select status, minutes_used, minutes_cap, period_end, cancel_at_period_end, stripe_subscription_id from subscriptions;"
```

Expected: `active`, `0`, `300`, a date one month ahead, `f`, and a `sub_...` id.

### 4. Use minutes, reach the cap, and reset

Voice sessions do not bill minutes yet (P7/P10 call `record_session_minutes`). Use the local-only
endpoint instead. In the browser console on http://localhost:5180:

```js
await fetch("/api/billing/dev/usage", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ minutes: 45 }) }).then(r => r.json())
```

Expected: `minutes_used: 45`, `minutes_left: 255`. Run it again with `minutes: 255`. Expected:
`can_start_session: false`, `block_code: "minutes_exhausted"`.

Start a new billing period to check the reset (use the `sub_...` id from step 3):

```powershell
stripe subscriptions update sub_XXXX -d billing_cycle_anchor=now -d proration_behavior=none
```

Expected: a `customer.subscription.updated` event, and `GET /api/billing/usage` shows
`minutes_used: 0` and a new `period_end`.

### 5. Idempotency

Copy an event id (`evt_...`) from the `stripe listen` window, then:

```powershell
stripe events resend evt_XXXX
```

Expected: the API log shows `duplicate=True`, and the subscription row does not change.

### 6. Cancel

1. Open http://localhost:5180/account and select Cancel plan.
2. Answer the 2 survey questions and select Continue to cancel. The Stripe portal opens.
3. Confirm the cancellation in the portal and return to the account page.
4. Expected: "Plan ends on" with the period end date, and `cancel_at_period_end` is `t`.
5. To end it now instead of at the period end:

```powershell
stripe subscriptions cancel sub_XXXX
```

Expected: a `customer.subscription.deleted` event, the meter says "Free plan: free interview
used" (or 1 left if you never started one), and `status` is `canceled`.

Check the survey:

```powershell
docker compose -f infra/compose.yaml --env-file .env exec postgres psql -U strong -c "select reason, got_job, reason_detail from exit_surveys;"
```

### 7. Delete the account

On the account page, type DELETE and select Delete my account. Then:

```powershell
stripe customers retrieve cus_XXXX
docker compose -f infra/compose.yaml --env-file .env exec postgres psql -U strong -c "select action, actor, at from audit_logs order by at desc limit 5;"
```

Expected: the customer shows `"deleted": true`; the audit log has `account.deleted` (and
`account.files_deleted` when the user had resume files); no row has the email.

## Privacy notes (AC-1)

- Delete removes every row in `USER_OWNED_TABLES` for the org, then the org, in one transaction.
  New user-owned tables are covered once they are added to `USER_OWNED_TABLES`.
- Resume files are deleted by the `delete_account_files` worker job. On a storage error it
  retries up to 10 times over about 7.5 hours, inside the 24-hour promise.
- AuditLog rows stay after the delete, with the email replaced by `user:<id>`.
- Database backups are not changed. They expire on their normal rotation, 30 days at most.
- A finished export waits in Redis for up to 24 hours, then expires. The first download
  deletes it.
- Arq keeps the resume upload job (with the file bytes) in Redis for 24 hours (P2 setting).
