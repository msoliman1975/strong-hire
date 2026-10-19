# Strong Hire Admin: Product & Technical Spec v0.1 (draft)

Status: v1, agreed 2026-10-17. Decisions D-1 to D-12 below.
This spec extends `docs/spec.md` (AD-1, AD-2, "least-privilege admin roles", AuditLog) and replaces
the admin parts of the L05 and L08 launch prompts where they conflict.

## Overview

Strong Hire Admin is a separate web app at `admin.getstronghire.com`. Only admins can use it. It
does three jobs:

1. **Support:** find a user, see what happened to them, and fix it (minutes, plan, access).
2. **Content:** run company profiles (AD-1) and the company-request backlog from a screen, not a CLI.
3. **Operations:** see whether the service is healthy, what it costs, and how well it performs, and
   get an email when something is wrong. Use kill switches when something goes badly wrong.

Everything is built in the app, on Postgres and Redis. There is no Grafana, Prometheus, Loki or
Sentry. We need a small number of service-specific views and alerts, not a general metrics
platform.

### Decisions so far

| ID | Decision |
| --- | --- |
| D-1 | Separate app, `apps/admin`, on its own subdomain. The R2 admin pages move out of `apps/web`. |
| D-2 | One admin tier. The admin list moves from `ADMIN_EMAILS` into the database. |
| D-3 | Observability is built in the app. A small set of metrics, health checks and an error inbox, not a Grafana replacement. |
| D-4 | A simple alert engine: threshold rules checked every minute, sent by email. |
| D-5 | v1 actions: user support, content and profiles, ops controls. Privacy requests stay self-serve in the candidate app: `POST /account/export` and `DELETE /account` already exist. |
| D-6 | Daily spend cap defaults to $25 for the beta, with an alert at 80% (was OQ-2). |
| D-7 | No refunds in the admin app for the beta. Refunds are made in the Stripe dashboard (was OQ-5). |
| D-8 | Admins never see resume or gap analysis content, only metadata (was OQ-7). |
| D-9 | Admin sign-in is Google or magic link with no extra factor for now (was OQ-1, option A). Revisit before a second person gets admin access. |
| D-10 | All alerts go to one ops address, `ALERT_EMAIL` (was OQ-3). |
| D-11 | No runtime model-profile switch. Changing the profile is an `.env` edit and a restart; the admin app shows what runs (OC-6). Provider outages are covered by LiteLLM fallbacks: each alias in `config/litellm.<profile>.yaml` may name a backup model (was OQ-4). |
| D-12 | Self-hosted speech is costed three ways, kept apart: session cost counts metered providers only ($0 marked self-hosted); the overview shows a separate "server share per session" from `INFRA_MONTHLY_USD`; the Spend page shows a "hosted equivalent" from shadow per-unit prices in config (was OQ-6). |
| D-13 | Admin-started AI interviews run in a `sim` service on the main server, one at a time. `sim-run.ps1` and the short-lived sim server stay for suites (SM). |
| D-14 | The admin starts one interview at a time from a form, with the 6 fixture personas. No pasted postings. |
| D-15 | The replay page shows audio and a synced transcript, the scorecard, the judge verdicts with links to times, and a response-time marker on each interviewer turn. |
| D-16 | While a run is in progress the admin sees its status and can cancel it. No live transcript or listen-in. |
| D-17 | Live users come first: the `sim` container is capped at 2 CPUs and 2 GB, a Controls switch pauses runs, and a run does not start while 3 or more real sessions are live (setting). |
| D-18 | Runs are kept under 10 GB and 90 days, oldest first. The admin can mark a run Keep (never deleted automatically) or delete it now. |

### Non-goals (v1)

- More than one role or per-permission access.
- A log search or log viewer. Logs stay in `docker logs` and `./scripts/dev.ps1 logs`.
- Arbitrary queries or ad-hoc charts. Every chart is a fixed view.
- Editing the question bank. It is file-based and lives in git (`feat/qb-*`). The admin app shows it read-only.
- Switching `MODEL_PROFILE` at runtime (D-11).
- Admin actions on behalf of a user inside the candidate app ("impersonation").
- Sentry or another error SaaS. A small in-app error inbox replaces it.

## Users of the app

Today this is the founder. Soon it may include one or two support or ops people. All of them have
the same rights (D-2), so the safeguards are a recorded reason, the audit log, and confirmation on
destructive actions, not roles.

## Architecture

```
            admin.getstronghire.com                    getstronghire.com
                     |                                        |
               Caddy  (admin site block)               Caddy  (main site block)
               /        \                              /            \
     /srv/admin (SPA)   /api/*  ──► api:8000 ◄──  /api/*        /srv (SPA)
                                     │            /api/admin/* -> 404 (blocked on main host)
                                     │
             Postgres (admin tables, ops_samples, alerts, errors)   Redis (heartbeats, flags cache)
                                     ▲
             worker cron: sampler (1 min), alert evaluator (1 min), retention (daily)
             api / worker / voice: heartbeat, error capture, runtime flags reader
```

- **Front end:** `apps/admin`, React + Vite + TypeScript, set up like `apps/web` (same lint and test tooling). It shares no runtime code with `apps/web`. Copying a few UI primitives is fine. A shared package can come later if the copies drift.
- **API:** the same FastAPI service. The admin routes stay in `strong_api.admin`, grow into sub-routers (`users`, `sessions`, `content`, `ops`, `alerts`, `auth`), and keep the `/admin` prefix.
- **Serving:** `infra/docker/caddy.Dockerfile` builds both SPAs. `infra/caddy/Caddyfile` gets an `admin.{$DOMAIN}` block with its own `/api/*` proxy and SPA fallback. The main block returns 404 for `/api/admin/*`, so the candidate origin can never reach admin routes. DNS needs an A record for `admin`.
- **Local dev:** `apps/admin` on port 5181 with a Vite proxy to the API. Add `http://localhost:5181` to CORS. `dev.ps1` gets `admin` targets for test and lint.

## Access and security (AA)

The candidate session today is a signed cookie (`sh_session`, 14 days, host-only) that the server
cannot revoke. That is not good enough for admins, so admin access gets its own server-side session.

| ID | Requirement | Priority |
| --- | --- | --- |
| AA-1 | Admins are rows in `admin_users` (email, added_by, added_at, disabled_at). `strongctl admin add/remove/list` manages them. On first start, if the table is empty, it is seeded from `ADMIN_EMAILS`; after that the env var is ignored. | P0 |
| AA-2 | Admin sign-in on the admin host, by Google OAuth, email magic link or password (AC-4). Both check `admin_users`. A link is sent only to an active admin; the screen shows the same message either way. | P0 |
| AA-3 | Admin sessions are rows in `admin_sessions` (id, admin_user_id, created_at, last_seen_at, expires_at, ip, user_agent, revoked_at). The cookie `sh_admin` holds only the session id. It is host-only on `admin.` and Secure, HttpOnly, SameSite=Strict. Idle timeout 2 h, absolute 12 h. | P0 |
| AA-4 | Every `/admin/*` route needs a live admin session. Without one: 404 for API calls (as today), and the SPA shows sign-in. A candidate `sh_session` never grants admin access, even for an admin's email. | P0 |
| AA-5 | Mutating admin routes need the `X-Admin-Request: 1` header and a JSON body (CSRF defense on top of SameSite=Strict). | P0 |
| AA-6 | Every mutating action takes a required free-text `reason` and writes an `audit_logs` row: actor = admin email, action, entity, before/after in `details_json`. Every view of a transcript, trace or audio is still audited (R2 rule). | P0 |
| AA-7 | Destructive actions (suspend, kill switches, publish profile, removing a grant) show a confirm dialog that repeats the target and amount. Pausing sessions also makes the admin type the word `PAUSE`. | P0 |
| AA-8 | An admin can see their own sessions and revoke them. Removing an admin revokes all of their sessions. | P1 |
| AA-9 | Strict CSP on the admin host (`default-src 'self'`), `X-Frame-Options: DENY`, no third-party scripts. | P0 |
| AA-10 | The R2 consent rule stays: transcripts and traces are visible only while the user's training consent is on. | P0 |
| AA-11 | Admins never see resume or gap analysis content (D-8): no resume text, file, extracted fields, gap findings, scores or brief. The API has no admin route that returns them, and a test checks that no admin response schema contains those fields. | P0 |

Sign-in hardening (D-9): for now an admin is as safe as their email or Google account. Options for
later, cheapest first:
- 2-step verification on the Google account (a habit we can't enforce).
- A TOTP or passkey second factor in the admin app (enforced, about a day of work).
- Admin host reachable only over Tailscale.

## Information architecture

```
Overview        funnel, revenue, usage, cost, quality (AD-2)
Users           search -> user detail -> actions
Interviews      list -> detail (transcript, traces, latency, cost breakdown)   [R2, moved]
Content         Companies & profiles · Company requests · Question bank (read-only)
Operations      Health · Errors · Jobs · Controls
Simulations     runs list + new run form -> run detail (replay)                   [SM]
Alerts          Rules · History
Audit log       [R2, moved]
Settings        Admins · My sessions
```

## Overview dashboard (AD-2)

This page takes over the L05 "admin overview" step. L05 keeps the event tracking, consent and rating
work; the overview page is built here, in `apps/admin`.

| ID | Requirement | Priority |
| --- | --- | --- |
| AO-1 | Ranges of 24 h, 7, 30 and 90 days, each compared with the previous period of the same length. | P0 |
| AO-2 | **Funnel:** sign-ups, activation (gap analysis done), free interview done, paid within 14 days, with conversion between steps. | P0 |
| AO-3 | **Revenue:** active paid subscribers, MRR, new subscriptions, cancellations, monthly churn, refunds. | P0 |
| AO-4 | **Usage:** sessions started, completed and failed, minutes, sessions per paid user, voice and text split. | P0 |
| AO-5 | **Cost:** total model cost per day, broken down by component (llm, stt, tts) and by role, plus cost per completed session (spec target: under $0.80). | P0 |
| AO-6 | **Quality:** session failure rate (target under 2%), voice latency p50/p95 (targets 800 ms and 1.5 s), realism rating average (L05). | P0 |
| AO-7 | Each number links to the filtered list behind it (for example, failed sessions to Interviews with status=failed). | P1 |
| AO-8 | Metrics the app cannot measure yet are shown as "not measured" with the reason. They are never hidden. | P0 |

## Users and support (AU)

| ID | Requirement | Priority |
| --- | --- | --- |
| AU-1 | Search users by email, name or id. Filter by plan, status (active, suspended), sign-up date and last sign-in. | P0 |
| AU-2 | **User detail:** profile, org, auth provider, consents, subscription and Stripe ids (linked to the Stripe dashboard), entitlement (minutes left, free interviews left, grants), sessions, job targets (company, title, level), cost to date, and the audit log entries about this user. For resumes and gap analyses, metadata only (D-8): count, created and deleted dates, status and error state, so support can see that a gap analysis failed without seeing its content. | P0 |
| AU-3 | **Grant minutes:** add or remove minutes with a reason and an optional expiry. Grants are rows in `minute_grants`, and entitlements count them on top of the plan. Grants are never written into `subscriptions`. | P0 |
| AU-4 | **Grant free interviews:** add to the user's free-interview allowance. Uses the same ledger with `kind=free_interviews`. | P0 |
| AU-5 | **Comp plan:** give paid access until a date without Stripe. This is a `minute_grants` row with `kind=comp_plan`, a cap and `expires_at`. Entitlements treat an active comp like an active subscription. It replaces `infra/server/grant-test-plans.sh`. | P0 |
| AU-6 | **Refunds (D-7):** made in the Stripe dashboard, not in the admin app. User detail links straight to the Stripe customer. The webhook handles `charge.refunded`, so refunds show on the user detail and in AO-3. | P1 |
| AU-7 | **Suspend / unsuspend:** sets `users.suspended_at` and `suspended_reason`. A suspended user's requests get 403 with a neutral message, and sessions in progress end cleanly. | P0 |
| AU-8 | **Force sign-out:** bumps `users.session_epoch`. The candidate cookie carries the epoch, and `optional_user` rejects a stale one. This also gives candidate sessions server-side revocation. | P0 |
| AU-9 | **Resend sign-in link** to the user's email. Rate-limited the same way as the public endpoint. | P1 |
| AU-10 | Admins see users' privacy actions (export, delete) in the audit log but do not run them (D-5). | P0 |

## Interviews (moved from R2)

The pages and API move to `apps/admin` with the same behavior, plus:

| ID | Requirement | Priority |
| --- | --- | --- |
| AI-1 | Status filter, including failed and "stuck" (status `scoring` or `in_progress` for longer than duration + 15 min). | P0 |
| AI-2 | Cost breakdown per session for every component and role (needs OB-2). | P0 |
| AI-3 | Per-turn voice latency table and a p50/p95 summary (needs OB-3). | P0 |
| AI-4 | The derived failure reason (`sessions/failure.py`) shown in the list and on the detail page. | P0 |

## Content (AT)

| ID | Requirement | Priority |
| --- | --- | --- |
| AT-1 | **Companies:** list with active flag, published version, draft count and request count. Turn a company on or off. | P0 |
| AT-2 | **Profile versions:** list per company. View the JSON and its sources, and diff any two versions (reuses `profiles/diff.py`). | P0 |
| AT-3 | **Import:** upload a profile JSON. It is validated against the schema (same code as `strongctl profiles validate`) and stored as a `draft` with sources and import date (AD-1). | P0 |
| AT-4 | **Workflow:** draft → in_review → published → archived. Publishing asks for confirmation, records `reviewed_by`, archives the previous published version, and is audited. Rollback means re-publishing an archived version. | P0 |
| AT-5 | **Company requests:** grouped by normalized name, with distinct users, first and last requested, and source hosts. Triage states: new, planned, declined, added (linked to a company). A new `company_request_triage` table holds them; request rows are not edited. | P1 |
| AT-6 | **Question bank:** read-only browser over the file-based bank once `feat/qb-*` merges. Editing stays in git. | P2 |

The CLI (`strongctl profiles ...`) stays, and both paths share the same repository code.

## Observability (OB)

The aim is to answer five questions from one place:
- Is it up?
- Is it fast?
- Is it failing?
- What does it cost?
- What broke?

### What we collect

| ID | Requirement | Priority |
| --- | --- | --- |
| OB-1 | **Heartbeats:** api, worker and voice each write `heartbeat:<service>:<instance>` to Redis every 15 s (TTL 60 s), with version, model profile and start time. A missing heartbeat means the service is down. | P0 |
| OB-2 | **Complete cost:** `usage_events` gets a `role` column (extractor, planner, interviewer, scorer, stt, tts), and every gateway call writes a row, including gap analysis, brief, extraction and scoring. Rows with no session have `session_id` NULL. The gateway does this, so no caller can skip it. Speech cost uses a per-unit price from config when the provider is metered, else 0 with `cost_known=false` (D-12). | P0 |
| OB-3 | **Voice latency:** voice interviews persist per-turn timings (e2e, turn_detection, stt, llm_ttft, tts_ttfb, other) to `voice_turn_timings` (user-owned, org_id, 90-day retention like traces). | P0 |
| OB-4 | **Errors:** a logging handler in api, worker and voice captures unhandled exceptions and `ERROR` logs into `error_events`, grouped by fingerprint (exception type + top in-app frames). Each group keeps a count, first and last seen, service, release and one sample stack. It scrubs PII before writing: no request bodies, emails, resume or transcript text (same rules as L05's Sentry `before_send`, with the same test). | P0 |
| OB-5 | **Samples:** a worker cron every minute writes `ops_samples` rows (ts, metric, value, labels): dependency probe results and latency, queue depth, sessions in progress, disk %, memory %, load, DB size, and Redis memory. 30-day retention. | P0 |
| OB-6 | **Dependency probes:** Postgres, Redis, LiteLLM `/health`, LiveKit, STT, TTS, SMTP (connect only, every 10 min), and Stripe (time since the last webhook). | P0 |
| OB-7 | Logs move to JSON lines with `service`, `request_id` and `session_id` fields, so `docker logs` can be grepped by session. | P1 |

Host metrics come from inside a container: `/proc/meminfo` and `/proc/loadavg` show host values,
and disk is read with `shutil.disk_usage` on a mounted path for the Postgres volume and the root.
No extra agent is needed.

### What we show

| ID | Requirement | Priority |
| --- | --- | --- |
| OB-10 | **Health page:** one tile per service and dependency (up, degraded or down, last checked, version), plus host disk, memory and load with 24 h sparklines. | P0 |
| OB-11 | **Performance:** voice latency p50/p95 by component over time, LLM latency by role, and queue wait time. | P0 |
| OB-12 | **Errors inbox:** groups sorted by last seen, each with count, sparkline, service and sample. Mark resolved; a group that happens again reopens. | P0 |
| OB-13 | **Jobs:** current queue depth, gap analyses and scorings that failed or are stuck, with **Retry** (re-enqueue, audited). Built from domain status columns, because Arq results are not persisted. | P0 |
| OB-14 | **Spend:** today's and this month's model cost against the cap (AO-5, OC-3), the LiteLLM budget view now at `/dev/model-usage`, and the "hosted equivalent" of self-hosted speech from shadow prices (D-12). | P0 |
| OB-15 | **Server share:** `INFRA_MONTHLY_USD` divided by the month's completed sessions, shown on the overview as its own line next to model cost per session, never added into session rows (D-12). | P1 |

Charts follow the dataviz guidance: fixed views, light and dark themes, no chart library beyond
what the web app already uses.

## Alerts (AL)

A small engine, not Alertmanager.

| ID | Requirement | Priority |
| --- | --- | --- |
| AL-1 | `alert_rules`: name, metric, aggregation (last, avg, p95, rate, count), window, comparator, threshold, minimum sample count, "for" duration, severity (critical, warning), re-notify interval, enabled. Every alert goes to the single `ALERT_EMAIL` address (D-10). | P0 |
| AL-2 | A worker cron runs every minute, evaluates each enabled rule over `ops_samples` and the domain tables, and moves it through ok → pending → firing → ok. | P0 |
| AL-3 | An email goes out on firing and on resolved. A rule that is still firing re-sends at its re-notify interval (default 4 h for critical, 24 h for warning). Each email says the rule, the value, the threshold, the start time, and links to the admin page. | P0 |
| AL-4 | `alert_events` keeps the history (rule, state change, value, at, notified). Alerts page: rules (edit, enable, mute until) and history. | P0 |
| AL-5 | Email goes through a generic `EmailSender.send(to, subject, text)` added next to `send_magic_link`. If sending fails, the event is stored as not notified and retried next tick. | P0 |
| AL-6 | A "send test alert" button for each rule. | P1 |
| AL-7 | An optional daily digest at 08:00 in the admin's time zone: yesterday's key numbers, open alerts and new error groups. | P2 |
| AL-8 | **Dead-man check:** the in-app engine cannot report the whole server or its own worker being down. An external free uptime checker on `/api/health` (L08) stays. `/api/health` also fails when the worker heartbeat is missing, so that checker covers the alert engine too. | P0 |

### Default rules (seeded, editable)

| Rule | Condition | Severity |
| --- | --- | --- |
| API down | `/health` probe failing for 2 min | critical |
| Worker or voice down | heartbeat missing for 2 min | critical |
| Dependency down | any OB-6 probe failing for 3 min | critical |
| Disk filling | disk over 85% | warning; over 95% critical |
| Memory pressure | memory over 90% for 10 min | warning |
| Session failures | failure rate over 5% in 1 h, at least 5 sessions | critical |
| Voice slow | e2e p95 over 1.5 s for 30 min, at least 20 turns | warning |
| Scoring stuck | any session in `scoring` for over 15 min | warning |
| Spend high | today's model cost over 80% of the daily cap | warning; 100% critical |
| New error | a new error fingerprint seen | warning (no re-notify) |
| Stripe silent | no webhook for 48 h while there are active subscriptions | warning |

## Ops controls (OC)

Runtime settings without a redeploy. A `runtime_settings` table (key, value_json, updated_by,
updated_at) holds them. Services read them through a small helper in `strong_core` with a 10 s
in-process cache. Every change is audited and shows as a banner in the admin app.

| ID | Requirement | Priority |
| --- | --- | --- |
| OC-1 | **Pause sign-ups:** new accounts are refused with a waitlist message. Existing users can still sign in. | P0 |
| OC-2 | **Pause new sessions,** per channel (voice, text): starting a session returns a friendly "temporarily unavailable". Sessions in progress continue. | P0 |
| OC-3 | **Daily spend cap (USD, default $25 for the beta, D-6):** when today's model cost reaches it, new sessions are refused (as in OC-2) and the Spend high alert fires. Sessions in progress always finish. | P0 |
| OC-4 | **Site banner:** text, severity and end time, shown in the candidate app. | P1 |
| OC-5 | **Pause background jobs** by type (gap analysis, scoring): jobs wait in the queue rather than run, for incidents with a model provider. | P2 |
| OC-6 | **Model profile:** read-only. Shows the running profile per service and per-role models (from `config/models.<profile>.yaml`) and flags a mismatch between services (D-11). | P1 |

## Simulations (SM)

An admin starts an interview between the AI interviewer and the AI candidate (P13,
`docs/sim-candidate.md`). It runs in the background on the main server, with audio. When it
ends, the admin replays it: the recording plays and the transcript follows it, next to the
scorecard, the judge's verdicts and the interviewer's response time on each turn. Decisions D-13
to D-18.

### How it runs

```
 admin app ── POST /admin/sim/runs ──▶ api ── checks (SM-3) ──▶ sim_runs row (queued)
                                                                       │
 sim service (main server, 2 CPUs, 2 GB)  ◀────────────────────────────┘  oldest queued row first
   - signs in with sim-login and runs the interview through the public URL, as a browser does
   - candidate and judge through the main LiteLLM with SIM_LITELLM_KEY (the $5/day sim budget)
   - candidate voice from the main server's Kokoro (tts service)
   - writes /srv/stronghire/sim/<run-id>/ (read-write mount); status and progress in sim_runs
```

- The `sim` service is `apps/sim` in a new mode, `strong-sim serve`: one loop that takes the
  oldest queued or waiting `sim_runs` row every 2 s and runs it; one run at a time. `sim_runs` is
  the queue: the api only writes rows, and cancel (SM-5) and delete (SM-13) are columns the loop
  reads. No Arq job, so nothing can get out of step between Redis and the table. It is in
  `compose.server.yaml` under the `sim` profile, with `cpus: 2` and `mem_limit: 2g`. Runs fail at
  the gate unless `SIM_ENABLED=true`. A restart fails the run that was active (its session and
  audio are gone).
- The interview itself still goes through HTTP and LiveKit like a real browser, so a run tests the
  real path. The service reads and writes `sim_runs` directly (it has `DATABASE_URL`).
- Models: the main `config/litellm.<profile>.yaml` gets the `sim-candidate`, `sim-judge` and
  `sim-tts` aliases, and the main LiteLLM gets `GEMINI_API_KEY`. The sim calls them with
  `SIM_LITELLM_KEY`, so LiteLLM enforces the $5/day budget on both sides. In this mode the sim
  must **not** call `POST /auth/sim-spend` (it would count the cost twice).
- `sim-run.ps1` suites on the short-lived server keep working as before. Their runs appear in the
  list too, read from disk (SM-12).

### Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| SM-1 | **New run form:** persona (the 6 resume fixtures; the posting and level follow), interview type, difficulty, mode, duration (10, 30 or 45 min, the lengths the app offers; 10 is a mini interview), candidate quality, behavior (voice-only behaviors only when channel is voice) and channel (voice by default). The form shows the cost estimate for the chosen duration, what is left of today's sim budget, and the current gate state (SM-3). | P0 |
| SM-2 | **Start:** creates a `sim_runs` row (`queued`), writes an audit row, and returns the run. At most one run is active; up to 5 more wait in the queue in order. | P0 |
| SM-3 | **Gates,** checked when the admin clicks Start (409 with a reason the form shows) and again when the job begins: `SIM_ENABLED` is on; the `sim_paused` setting is off; fewer than `sim_max_live_sessions` (default 3) real sessions are `in_progress` (the sim org does not count); the estimate fits what is left of today's sim budget. At job start, a failed live-sessions gate sets the run to `waiting` and checks again every 60 s; after 30 min it fails with the reason. The other gates fail the run at once. | P0 |
| SM-4 | **Status:** `queued → waiting → starting → interviewing → judging → done`, or `failed` (with the error) or `cancelled`. While `interviewing`, the row shows elapsed / planned minutes, updated every 10 s. Cost so far = sim side (from the sim's meter) + app side (`usage_events` of the session). The list polls every 5 s while any run is not finished. | P0 |
| SM-5 | **Cancel:** sets `cancel_requested_at`. A queued or waiting run is cancelled at once. An active run ends its session on the server within 5 s, saves the transcript and audio so far, skips the judge, and ends `cancelled`. Audited. | P0 |
| SM-6 | **Audio-clock timing (apps/sim):** in voice runs, every `start_ms`/`end_ms` is measured from the first sample of `audio.ogg`. Interviewer line: start = the first loud frame on the left channel after the previous candidate line ended; end = the last loud frame before the next candidate line starts. Candidate line: start and end = first and last frame the candidate's mic track sent. Each interviewer line also gets `latency_ms` = its start − the previous candidate line's end. `meta.json` gets `"timing": "audio"`. A test with a synthetic recording checks the times within 150 ms. | P0 |
| SM-7 | **Replay player:** play/pause, back/forward 10 s, speed 1×, 1.25×, 1.5×, 2×, a scrubber with markers for slow turns and judge problems. "Mixed" (default: both voices in both ears) or "Stereo" (interviewer left, candidate right) through Web Audio. The audio route supports HTTP Range so seeking works without downloading the file. | P0 |
| SM-8 | **Synced transcript:** each line shows its time, speaker and phase. The line being played is highlighted and kept in view; scrolling by hand stops the auto-scroll until "Follow" is clicked. Clicking a line's time seeks there and plays. Keys: space play/pause, ←/→ 10 s, J/K previous/next line, N next slow turn. Runs without `"timing": "audio"` (older runs) show "times are approximate". Text runs show the same transcript without a player. | P0 |
| SM-9 | **Response time:** a chip before each interviewer line shows `latency_ms`: green under 800 ms (the spec's p50 budget), amber 800–1500 ms, red over 1500 ms. The header shows p50 and p90 for the run and the number of red turns. | P0 |
| SM-10 | **Judge panel:** each rule with pass/fail/n/a and the reason, and the problems list. Every `mm:ss` in a reason or a problem's `at` is a link that seeks the player. | P0 |
| SM-11 | **Scorecard panel:** the debrief's hire signal, competency scores and evidence, as the candidate would see them. | P0 |
| SM-12 | **Runs list:** started by, scenario summary, status, length, hire signal, failed judge rules, p50 response time, cost, Keep. Filters: status, channel, started by admin or by suite. Runs from `sim-run.ps1` are read from disk and shown with "suite" as the source; they open in the same replay page (with "times are approximate" when they predate SM-6). | P1 |
| SM-13 | **Keep and Delete:** Keep marks a run so retention never deletes it. Delete (with a reason and confirmation) deletes the run folder at once and sets `deleted_at` on the row, so the list and costs keep a stub. The interview session itself stays in Interviews. Both audited. | P0 |
| SM-14 | **Retention** moves from the host cron into the `sim` service (hourly): delete run folders older than `SIM_KEEP_DAYS` (default 90), then the oldest until under `SIM_KEEP_GB` (default 10). It skips runs marked Keep and the newest run, and records each deletion on the run's row. `infra/sim/server-setup.sh` stops installing the host cron. | P0 |
| SM-15 | **Controls:** "Pause sim runs" (`sim_paused`) and "Live sessions limit for sim runs" (`sim_max_live_sessions`, 0–20) on the Controls page, audited like OC-1..OC-5. Pausing also offers "stop the active run" (= SM-5). | P0 |
| SM-16 | **Interview page link:** an interview of the sim user that has a run folder shows "Replay". | P1 |

## Data model changes

These are all in `packages/core`, so they go in one small shared PR that merges first (the CLAUDE.md
rule). The new user-owned tables have `org_id` and go in `USER_OWNED_TABLES`.

| Table / column | Kind | Notes |
| --- | --- | --- |
| `admin_users` | new, platform | email unique, added_by, added_at, disabled_at |
| `admin_sessions` | new, platform | see AA-3 |
| `users.suspended_at`, `suspended_reason`, `session_epoch` | columns | AU-7, AU-8 |
| `minute_grants` | new, user-owned | kind (minutes, free_interviews, comp_plan), amount, expires_at, reason, granted_by, created_at |
| `usage_events.role`, `cost_known` | columns | OB-2 |
| `voice_turn_timings` | new, user-owned | OB-3, 90-day retention |
| `error_events` / `error_groups` | new, platform | OB-4, 30-day retention for events, groups kept |
| `ops_samples` | new, platform | OB-5, 30-day retention, index (metric, ts) |
| `alert_rules`, `alert_events` | new, platform | AL-1, AL-4 |
| `runtime_settings` | new, platform | OC |
| `company_request_triage` | new, platform | AT-5 |
| `sim_runs` | new, user-owned (the sim org) | SM: id, org_id, scenario_json, status (enum, SM-4), status_reason, run_dir, session_id (nullable FK), created_by (admin_users), created_at, started_at, finished_at, progress_s, cost_sim_usd, cancel_requested_at, keep, deleted_at, deleted_by, delete_reason |
| `runtime_settings` keys `sim_paused`, `sim_max_live_sessions` | settings | SM-15 |

Platform tables have no `org_id`. The ownership test needs an explicit `PLATFORM_TABLES` list
next to `USER_OWNED_TABLES`, so every table is classified on purpose.

Volume check: `ops_samples` is about 30 metrics × 1,440 per day × 30 days ≈ 1.3 M rows. That is
fine for Postgres with one index, deleted daily in batches.

## API surface (new or changed)

All routes are under `/admin`, use the admin session (AA-4), and mutating routes follow AA-5/AA-6.

```
POST   /admin/auth/google | /admin/auth/link | /admin/auth/link/verify | /admin/auth/signout
GET    /admin/me                       GET/DELETE /admin/me/sessions[/{id}]
GET    /admin/overview?range=          (AO)
GET    /admin/users?q=&plan=&status=   GET /admin/users/{id}
POST   /admin/users/{id}/grants        DELETE /admin/users/{id}/grants/{grant_id}
POST   /admin/users/{id}/suspend | /unsuspend | /signout | /resend-link
GET    /admin/sessions ...             (R2, plus status and stuck filters, cost breakdown, latency)
GET    /admin/companies                PATCH /admin/companies/{slug}
GET    /admin/companies/{slug}/profiles          POST (import)    GET .../{version}
GET    /admin/companies/{slug}/profiles/diff?a=&b=
POST   /admin/companies/{slug}/profiles/{version}/transition   {to: in_review|published|archived}
GET    /admin/company-requests         PUT /admin/company-requests/{normalized}/triage
GET    /admin/ops/health               GET /admin/ops/metrics?metric=&range=
GET    /admin/ops/errors               PATCH /admin/ops/errors/{group_id}
GET    /admin/ops/jobs                 POST /admin/ops/jobs/{kind}/{id}/retry
GET    /admin/ops/settings             PUT /admin/ops/settings/{key}
GET    /admin/alerts/rules             POST/PATCH/DELETE /admin/alerts/rules[/{id}]   POST .../{id}/test
GET    /admin/alerts/events
GET    /admin/admins                   POST/DELETE /admin/admins[/{id}]
GET    /admin/audit                    (R2)
GET    /admin/sim/options              personas, choices, estimates, budget left, gate state (SM-1)
GET    /admin/sim/runs?status=&channel=&source=      POST /admin/sim/runs   (SM-2, SM-3, SM-12)
GET    /admin/sim/runs/{id}            PATCH {keep}    DELETE {reason}        (SM-13)
POST   /admin/sim/runs/{id}/cancel     (SM-5)
GET    /admin/sessions/{id}/replay     transcript with times and latency, judge, scorecard, audio info (SM-7..SM-11)
GET    /admin/sessions/{id}/audio      now answers Range requests with 206 (SM-7)
```

Contracts for these responses live in `strong_api.admin.schemas`, not `strong_core.schemas`,
because no other service uses them. The admin app generates its TypeScript types from the API's
OpenAPI, as `apps/web` does.

## Delivery plan

| PR | Branch | Content | Depends on |
| --- | --- | --- | --- |
| A0 | `feat/a0-admin-core` | All data model changes, `runtime_settings` reader, `EmailSender.send`, gateway writes UsageEvent with role (OB-2) | none |
| A1 | `feat/a1-admin-shell` | `apps/admin` scaffold, admin auth and sessions (AA), Caddy and Dockerfile, CI, and R2 pages ported. R2 pages removed from `apps/web`. | A0 |
| A2 | `feat/a2-admin-users` | AU-1..AU-9, entitlements read `minute_grants`, session epoch and suspend checks in candidate auth | A1 |
| A3 | `feat/a3-observability` | Heartbeats, error capture, sampler and probes, voice latency persistence, retention jobs, `/health` checks worker heartbeat | A0 |
| A4 | `feat/a4-ops-pages` | Overview (AO), Health, Performance, Errors, Jobs and retry, Spend | A1, A3 (and L05 for rating and events) |
| A5 | `feat/a5-alerts` | Alert engine, default rules, Alerts pages | A3 |
| A6 | `feat/a6-ops-controls` | OC-1..OC-4 in api, voice and web, Controls page | A1 |
| A7 | `feat/a7-admin-content` | AT-1..AT-5 | A1 |
| S0 | `feat/s0-sim-core` | `sim_runs` model and migration, the two runtime settings | none |
| S1 | `feat/s1-sim-serve` | apps/sim: audio-clock timing (SM-6), `serve` mode with cancel, progress, gates at run start and retention (SM-3..SM-5, SM-14); infra: `sim` service, LiteLLM aliases, server-setup change | S0 |
| S2 | `feat/s2-sim-api` | Admin routes, gates at Start, replay route, audio Range (SM-1..SM-5, SM-7..SM-13) | S0 |
| S3 | `feat/s3-sim-web` | Simulations list and form, replay page, Controls additions, interview link (SM-1, SM-7..SM-16) | S2 |

A3 and A5 can run in parallel with A1 and A2. For the private beta on Nov 30 the minimum is A0, A1,
A3, A5 (to know when it breaks), A6 OC-1..OC-3 (to stop the bleeding) and AU-3/AU-5/AU-7 (to look
after beta users). The rest can land in December. `strongctl` covers content until A7 merges.

### Effect on the launch plan

- **L05:** keeps events, consent, rating and the marketing-site counting. Its admin overview step moves to A4, and its Sentry step is replaced by OB-4.
- **L08:** keeps the external uptime check (AL-8). It drops Grafana and the separate disk and memory alerts, which move to A3/A5.
- **`infra/server/grant-test-plans.sh`:** is replaced by AU-5 comp plans and then removed.

## Open questions

None. OQ-1 to OQ-7 were resolved as D-6 to D-12.
