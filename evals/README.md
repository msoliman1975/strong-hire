# Evals

The eval harness tells us whether the interviewer and the scorer are any good. It runs with any
model profile: `fake` (no model, used in CI), `local` (Ollama in Docker) or `hosted`.
Every prompt or model change re-runs the evals, including the scorer gold set (spec, Calibration).

The Python package is `strong_evals` (`evals/src`). All model calls go through
`strong_core.gateway`, like the rest of the code (PL-1).

## Run a suite

```powershell
./scripts/eval.ps1                                  # smoke suite on the fake model, no Docker
./scripts/eval.ps1 -Suite full                      # 30 transcripts and 12 simulated sessions
./scripts/models.ps1 pull                           # once, before the local profile
./scripts/eval.ps1 -Suite goldset -Profile local    # scorer calibration on local models
./scripts/eval.ps1 -Suite full -Profile local -Record -Gate
```

Each run writes `evals/reports/<suite>-<profile>-<time>.html` and a `.json` with the same data.
The report lists each metric with its value, its threshold, PASS or FAIL, and where the threshold
comes from. `-Gate` makes the run exit with code 1 when a metric fails. On the fake profile the
numbers only show that the harness works; the fake scorer gives the same scorecard every time.

Without PowerShell: `uv run python -m strong_evals run --suite smoke --profile fake`.

Suites live in `suites/<name>.yaml`:

| Suite | Contents |
| --- | --- |
| `smoke` | 4 scripted transcripts (one per interview type) and 2 short simulated sessions |
| `goldset` | All 30 scripted transcripts, scored and compared with the gold-set labels |
| `simulated` | 12 simulated sessions: 4 interview types times strong, average and weak answers |
| `full` | `goldset` plus `simulated` |

## Metrics and thresholds

Thresholds are in `config/thresholds.yaml`.

| Metric | How it is measured | Threshold |
| --- | --- | --- |
| Scorer agreement, within one band | Scorer hire signal versus the human gold-set signal | 85% or more (spec) |
| Scorer agreement, exact band | Same pairs, exact match | Information only |
| Rubric scores within one point | Per question and competency, scorer versus human | Information only |
| Follow-up rate on vague answers | Simulated sessions: vague answers that got a probe on the same question, while probes were left (IV-3) | 80% (harness default) |
| Coverage of target competencies | Simulated sessions: target competencies touched by the asked questions | 80% (harness default) |
| Cost per session | Simulated sessions: sum of `UsageEvent.cost_usd`, with STT and TTS estimated from the text | $0.80 or less (spec) |

Prices per gateway alias are planning estimates in `config/prices.yaml`. A vague answer is one
that misses two or more of: own role, measurable result, concrete example, trade-off reasoning
(`strong_evals.metrics.missing_elements`).

## Parts

- `transcripts/<id>.json`: 30 scripted interviews (`ScriptedTranscript`): the `InterviewerBrief`,
  the `Turn` list, and the indexes of vague candidate answers. 8 behavioral, 7 hiring manager,
  8 technical Q&A, 7 case; new grad, mid and senior; 10 strong, 10 average and 10 weak.
  The people and companies are made up.
- `goldset/labels/*.csv`: human scores, see below.
- Simulated candidate (`strong_evals.candidate`): plays a `Persona` built from a resume in
  `fixtures/inputs/resumes/` with a quality level. It uses the planner role and the prompts in
  `prompts/evals/`.
- `run_text_session(config, persona)` (`strong_evals.session`): a text-only interview with the
  session controller, an interviewer and the simulated candidate. P7 passes its interviewer with
  `interviewer=`; P8 scores the returned turns with its scorer.
- Stubs (`strong_evals.stubs`) stand in for the planner, interviewer and scorer until P6 to P8
  land. They sit behind the interfaces in `strong_evals.interfaces`.
- Fixture recorder (`strong_core.gateway.recorder`): `-Record` saves every model call of a run as
  a fixture that the fake model replays.

## Gold set: how to score transcripts

The seed labels (`rater = seed-author`) were written with the synthetic transcripts. Real
interviewers add their own files next to them. The spec asks for 60 to 100 scored transcripts.

1. Make your sheets: `uv run python -m strong_evals goldset sheet --rater <your-initials>`.
   This writes one readable `<id>.txt` per transcript and a `<your-initials>.csv` to fill, in
   `var/goldset-sheets/`.
2. In the CSV, give each asked question and competency a score from 1 to 4
   (1 = no evidence, 2 = weak, 3 = meets the bar for this level, 4 = above the bar).
   On the `overall` row, set `hire_signal` to Strong Hire, Hire, Lean Hire, Lean No Hire or
   No Hire. The `note` column is optional.
3. Copy the CSV to `evals/goldset/labels/` and run `uv run python -m strong_evals validate`.

With several raters, the harness uses the median per transcript. For an even count it takes the
more cautious of the two middle values.

## Input extraction fixtures (P2)

`fixtures/inputs/` holds the job posting and resume fixtures for the extractor. See
`fixtures/inputs/README.md`.
