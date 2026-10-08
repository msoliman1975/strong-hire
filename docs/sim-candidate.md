# AI candidate (P13)

The AI candidate takes practice interviews against the deployed app at
`https://getstronghire.com`, the same way a real user does. A judge model checks the interviewer
in each transcript. A report shows each judge rule, the hire signal, the session length, turn
latency and cost. Use it to find interviewer bugs and to check that the scorer ranks strong
answers above weak ones.

Runs are on demand only. Nothing runs on a schedule or in CI.

## How it works

```
 your machine                 sim server (cx33, nbg1)            stronghire-test (main server)
 sim-run.ps1  ── creates ──▶  sim container                      api, worker, voice agent
              ◀─ deletes ───   - candidate: Gemini 3.5 Flash ──▶  interviewer, scorer (Claude)
                               - judge: Sonnet 5.5          HTTPS, LiveKit
                               - Kokoro TTS (voice only)
                               - rsync each finished session ──▶ /srv/stronghire/sim/<run-id>/
```

- The sim server exists only during a run. `sim-run.ps1` creates it from a snapshot, runs the
  suite, and deletes it, also when the run fails. It costs $0.016 per started hour.
- The sim signs in through `POST /api/auth/sim-login` with the `X-Sim-Token` header. The route
  answers 404 unless the main server has `SIM_ENABLED=true` and a `SIM_TOKEN` of 32 or more
  characters. A wrong token also gets 404. After 5 wrong tokens from one address in 10 minutes,
  that address gets 404 for 10 minutes.
- The sim user (`SIM_EMAIL`, default `sim@getstronghire.com`) has its own org. Its sessions skip
  the plan check, may use the text channel on the server, use their own model budget (see
  Budget), and never mix with real users' data. Its minutes and progress snapshots stay in that
  org.
- The candidate model is a different provider from the interviewer on purpose
  (`config/models.sim.yaml`, `config/litellm.sim.yaml`). To switch provider, change
  `sim-candidate` in `litellm.sim.yaml` and pass the new key; no code changes.
- Voice sessions: the candidate reads the interviewer's words from the room's data channel (the
  same captions the web page shows), so the sim server needs no speech-to-text. It speaks with
  Kokoro (voice `am_michael`). It records what it hears (left channel) and what it says (right
  channel) into one stereo Ogg Opus file, about 11 MB for 30 minutes. The main server still
  stores no audio for any session.

## Saved results

Each run is saved on the main server in `/srv/stronghire/sim/<run-id>/`:

| File | What it holds |
| --- | --- |
| `report.html`, `report.json` | One row per session, the judge results and the scorer order check |
| `scenarios.yaml` | The exact scenarios that ran |
| `<session-id>/transcript.json`, `transcript.txt` | The conversation with times |
| `<session-id>/audio.ogg` | Voice sessions only |
| `<session-id>/judge.json` | The verdict for each rule, with reasons |
| `<session-id>/debrief.json` | The app's debrief, with the scorecard |
| `<session-id>/meta.json` | Scenario, models, prompt versions, notes, latency, cost |

Files are uploaded after each session, so a run that stops early keeps the sessions it finished.
A cron job keeps the folder under 10 GB (`SIM_KEEP_GB`) and deletes the oldest runs first. It
never deletes the newest run.

```powershell
./infra/sim/sim-list.ps1                       # saved runs: sessions, errors, passes, cost, size
./infra/sim/sim-fetch.ps1 <run-id>             # copy one run to .\sim-runs\<run-id>\
```

## Running a suite

```powershell
./infra/sim/sim-run.ps1 -Suite text-smoke                  # asks before it starts
./infra/sim/sim-run.ps1 -Suite text-behaviors -Scenario tb-03,tb-07 -LimitUsd 2
uv run --package strong-sim strong-sim plan --suite text-quality   # scenarios and estimate only
```

Suites are in `evals/scenarios/` (see its README). Text sessions finish in about 2 to 4 minutes
each. Voice sessions run in real time.

## Budget

AI-to-AI tests have their own budget: **$5 per day** for everything, separate from the app's
daily budget for real users.

- On the main server, the sim org's model calls (job and resume reading, gap analysis, interview
  plan, interviewer, scorer) use their own LiteLLM key, `SIM_LITELLM_KEY`, created with
  `max_budget` 5 and `budget_duration` 1d. LiteLLM refuses calls past the limit, so sim runs can
  never use the app key's budget. `strong_core.sim.gateway_for_org()` picks the key.
- The sim server's own calls (candidate on Gemini, judge on Sonnet) are counted by the sim and
  reported to `POST /auth/sim-spend` after each session.
- `GET /auth/sim-budget` adds both parts. Before each session the sim checks what is left; it
  does not start a session that would not fit, and it stops a session when the sim side passes
  what is left. `-LimitUsd` on `sim-run.ps1` is a lower limit for one run.

Rough model cost per 30-minute text session: candidate $0.17, judge $0.04, main server $0.08.
Check the report for the real numbers.

## Setup (once)

1. Main server `.env`: `SIM_ENABLED=true`, `SIM_TOKEN=<openssl rand -hex 32>`,
   `SIM_EMAIL=sim@getstronghire.com`, and `SIM_LITELLM_KEY` (a LiteLLM key made with the master
   key: `POST /key/generate` with `key_alias` "sim", `max_budget` 5, `budget_duration` "1d").
   `infra/compose.server.yaml` passes them to the api, worker and voice services.
2. Upload user on the main server:
   `bash infra/sim/server-setup.sh "<contents of ~/.ssh/stronghire_simup.pub>"`.
3. Your machine, user environment variables: `HCLOUD_TOKEN`, `GEMINI_KEY`, `ANTHROPIC_API_KEY`,
   `STRONGHIRE_SIM_TOKEN` (the same value as `SIM_TOKEN`). The upload key is
   `~/.ssh/stronghire_simup`.
4. `./infra/sim/sim-snapshot.ps1` builds the snapshot (about 15 minutes, once).

## Adding a scenario or a behavior

- Scenario: add a line to a suite file in `evals/scenarios/`.
- Behavior: add `prompts/candidate/behavior_<name>.v1.txt` and the name to `Behavior` in
  `apps/sim/src/strong_sim/scenarios.py`. If the harness must act on it (as for `silent`,
  `interrupts`, `drops_connection`), add that to `apps/sim/src/strong_sim/sessions.py`.
- Judge rule: change `prompts/judge/transcript.v<N+1>.txt` and `RULES` in `judge.py`.
