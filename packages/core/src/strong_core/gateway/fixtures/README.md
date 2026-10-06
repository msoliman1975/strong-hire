# Fake model fixtures

Used when `MODEL_PROFILE=fake` (tests and CI). See `strong_core/gateway/fake.py` for the lookup
order. Each JSON file must validate against the contract it is named after; a test checks this.

To record a real reply as a fixture, run a call through `strong_core.gateway.recorder` with
`MODEL_PROFILE=local` or `hosted`. It writes `<role>/<messages-hash>.json` with the request and the
response. The fake model replays it, including its token usage. The eval harness can record a whole
suite with `scripts/eval.ps1 -Profile local -Record`.
