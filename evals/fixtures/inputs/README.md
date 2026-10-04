# Input extraction fixtures (P2)

Fixtures for the job posting (IN-2) and resume (IN-3) extractor.

- `postings/<name>.txt` is a real-style job posting. `postings/<name>.json` is the expected
  `JobPosting`. There are 10 postings, 2 per role family (swe, data_ml, pm, design, tpm).
  Five are for curated companies and five are for companies that run in generic mode.
- `resumes/<name>.txt` is a synthetic resume. `resumes/<name>.json` is the expected `Resume`.
  The people, employers and schools are made up. Contact details use example.com.
- Two fixtures carry a planted instruction aimed at the model (`swe-northwind-newgrad` and
  `product-manager-mid`). The expected output ignores it.

Run the extraction accuracy report against real models (opt-in, needs the models profile):

```powershell
$env:MODEL_PROFILE = "local"; $env:STRONG_EVAL_INPUTS = "1"
uv run pytest apps/worker/tests/test_extraction_accuracy.py -s
# or
uv run python -m strong_worker.inputs.accuracy --out inputs-accuracy.json
```

Every expected file must validate against its contract. A test checks this in CI.
