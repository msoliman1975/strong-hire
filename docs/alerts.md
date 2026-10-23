# Alerts

The in-app alert engine (admin spec AL-1 to AL-7, D-4, D-6, D-10). It checks threshold rules every
minute and emails one address. It is not Alertmanager: one email address, fixed metrics, no
routing.

| Part | Where |
| --- | --- |
| Metric catalog, default rules, email text | `packages/core/src/strong_core/ops/alerts.py` |
| Engine (cron every minute), digest | `apps/worker/src/strong_worker/alerts/` |
| API (`/admin/alerts/*`) | `apps/api/src/strong_api/admin/alerts.py` |
| Pages (Alerts: Rules, History) | `apps/admin/src/pages/Alert*.tsx` |

## Settings

| Variable | Default | Use |
| --- | --- | --- |
| `ALERT_EMAIL` | empty | The one address every alert goes to (D-10). Empty: events wait, unsent, and retry. |
| `ADMIN_BASE_URL` | `http://localhost:5181` | Link to the Alerts page in each email. |
| `SMTP_*` | none | The worker sends through `strong_core.email`. Without `SMTP_HOST` emails go to the log. |
| `ALERT_DIGEST` | `false` | AL-7: send a daily digest. |
| `ALERT_DIGEST_HOUR_UTC` | `8` | AL-7: the hour (UTC) the digest goes out. |

The worker and the API both need `ALERT_EMAIL` (the API for the Test button).

## How a rule works

Each minute the worker's `evaluate_alerts` cron reads every enabled rule:

1. **Reading.** It takes the rule's metric over the last `window_s` seconds and reduces it with
   `aggregation`: `last`, `avg`, `p95` (nearest rank), `count` (number of samples) or `rate`
   (change per second between the first and the last sample).
   - Sampled metrics come from `ops_samples`. `labels` filters them: `{"mount": "root"}` or a list
     of values, `{"service": ["worker", "voice"]}`. With no filter every series counts. Each
     series (one set of labels) is aggregated on its own and the **worst** one counts: the highest
     for `>`/`>=`, the lowest for `<`/`<=`. So one rule covers "any dependency down".
   - **Up metrics** (`heartbeat.up`, `probe.up`): no data means down. A series the filter names
     with no sample in the window counts as one sample of 0, and so does a rule with no filter
     when no sample matched.
   - Derived metrics are computed from the domain tables, each with one fixed aggregation.
2. **Enough data?** With fewer than `min_samples` samples, or no value, nothing changes, not
   even a firing rule.
3. **Condition** `value <comparator> threshold`, then the state machine:

   | State | Condition true | Condition false |
   | --- | --- | --- |
   | ok | pending (firing at once when `for_s` is 0) | ok |
   | pending | firing once it has held for `for_s` | ok, no event |
   | firing | re-send every `renotify_s` (empty: never) | ok, `resolved` event |

4. **Email.** `fired` and `resolved` events go to `ALERT_EMAIL`:
   `[Strong Hire][CRITICAL] <rule> firing` or `... resolved`, with the value, threshold, start
   time and a link to the Alerts page. A failed send keeps `notified = false` with
   `notify_error`, and the next tick tries again (for a day).
5. **Mute.** A muted rule still changes state and writes events, but sends nothing; its events
   say `muted`. If it is still firing when the mute ends, a `fired` email goes out then.

Two worker instances never double-send: a tick runs under a Postgres advisory lock (and Arq
runs each cron tick once). A rule whose metric fails to read is logged and skipped; the others
still run.

**Disabling** a rule stops its checks and resets it to ok, without an email.

The engine runs in the worker, so it cannot report the worker or the whole server being down.
The external uptime check on `/api/health` covers that (AL-8).

## Metric catalog

Sampled (written by the sampler cron, OB-5):

| Metric | Labels | Notes |
| --- | --- | --- |
| `probe.up` | `dep`: postgres, redis, litellm, livekit, stt, tts, smtp | 1 up, 0 down. Up metric |
| `probe.latency_ms` | `dep` | |
| `heartbeat.up` | `service`: api, worker, voice | 1 up, 0 down. Up metric |
| `queue.depth` | `queue` | |
| `sessions.in_progress` | | |
| `host.disk_pct` | `mount`: root, pgdata | |
| `host.mem_pct` | | |
| `host.load1` | | |
| `db.size_bytes` | | |
| `redis.mem_bytes` | | |
| `stripe.webhook_age_s` | | Counts only while there is an active Stripe subscription; otherwise the rule is ok |

Derived (computed by the engine):

| Metric | Aggregation | Value; samples |
| --- | --- | --- |
| `sessions.failure_rate` | rate | % of interviews that ended in the window with status failed; samples = interviews ended |
| `voice.e2e_p95_ms` | p95 | p95 of `voice_turn_timings.e2e_ms` in the window; samples = turns |
| `sessions.scoring_stuck` | count | interviews in `scoring` for more than 15 minutes |
| `spend.today_usd` | last | model cost since UTC midnight |
| `spend.cap_pct` | last | that cost as a % of the runtime setting `daily_spend_cap_usd` (D-6: $25) |
| `errors.new_groups` | count | error groups first seen in the window |

## Default rules

The worker seeds these at startup, by name, when they are missing (`strong_core.db.seed` does
too). A rule an admin has edited is never overwritten. Default rules can be edited and disabled
but not renamed or deleted, so they are not seeded again.

| Rule | Condition | Severity, re-send |
| --- | --- | --- |
| API down | `last(heartbeat.up{service=api}) < 1` over 2 min, for 2 min | critical, 4 h |
| Worker or voice down | `last(heartbeat.up{service=worker\|voice}) < 1` over 2 min, for 2 min | critical, 4 h |
| Dependency down | `last(probe.up) < 1` over 15 min, for 3 min | critical, 4 h |
| Disk filling | `last(host.disk_pct) > 85` | warning, 24 h |
| Disk almost full | `last(host.disk_pct) > 95` | critical, 4 h |
| Memory pressure | `last(host.mem_pct) > 90`, for 10 min | warning, 24 h |
| Session failures | `sessions.failure_rate > 5` over 1 h, at least 5 interviews | critical, 4 h |
| Voice slow | `voice.e2e_p95_ms > 1500` over 30 min, at least 20 turns | warning, 24 h |
| Scoring stuck | `sessions.scoring_stuck > 0` | warning, 24 h |
| Spend high | `spend.cap_pct >= 80` | warning, 24 h |
| Spend cap reached | `spend.cap_pct >= 100` | critical, 4 h |
| New error | `errors.new_groups > 0` over 10 min | warning, never |
| Stripe silent | `stripe.webhook_age_s > 172800` (48 h), only with active subscriptions | warning, 24 h |

API down uses the API heartbeat, because the API writes it while it serves; the dependency probes
do not include the API.

## Adding a rule

- **From the admin app:** Alerts, New rule. Pick a metric, labels (`key=value`, `|` between
  values), the aggregation, window, threshold, minimum samples, "for" and re-send time. Every
  change asks for a reason and goes to the audit log. Use **Test** to check the email arrives.
- **A new default rule:** add a `DefaultRule` to `DEFAULT_RULES` in `strong_core/ops/alerts.py`.
  The next worker start adds it everywhere.
- **A new sampled metric:** add it to `_SAMPLED` in `strong_core/ops/alerts.py` (name, labels,
  `up=True` if missing data means down) and make the sampler write it.
- **A new derived metric:** add it to `_DERIVED` (with its aggregation) and a function to
  `DERIVED` in `strong_worker/alerts/readings.py`. A check fails at import when the two lists
  differ.
