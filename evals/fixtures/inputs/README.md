# Input extraction fixtures (P2)

Fixtures for the job posting (IN-2) and resume (IN-3) extractor.

- `postings/<name>.txt` is a real-style job posting. `postings/<name>.json` is the expected
  `JobPosting`. There are 10 postings, 2 per role family (swe, data_ml, pm, design, tpm).
  Five are for curated companies and five are for companies that run in generic mode.
- `resumes/<name>.txt` is a synthetic resume. `resumes/<name>.json` is the expected `Resume`.
  The people, employers and schools are made up. Contact details use example.com.
- `resumes/<name>.pdf` and `resumes/<name>.docx` are synthetic CV files with layouts that a
  text reader can get wrong: a date column on the left (`date-column`, drawn in the order of a
  real failure), a sidebar (`sidebar-two-column`), bold sub-sections (`bold-subsections`,
  `docx-bold-subsections`), a ruled table (`table-layout`), a role split across two pages
  (`multipage-split-role`), two roles at one company (`same-company-two-roles`), a DOCX table
  (`docx-table`) and a DOCX text box (`docx-textbox-sidebar`). Do not edit them by hand.
  Rebuild them and their expected JSON with
  `uv run python evals/fixtures/inputs/build_resume_files.py` (needs the dev dependencies).
- The accuracy runner reads every input through `document_text`, as the worker does. Besides
  the per-field scores it reports `achievement_attribution` (an achievement counts only under
  the right role: same company, same start or end year), `reading_order` and `text_coverage`.
  The last two need no model: they check the reader's text against the expected JSON.
- Two fixtures carry a planted instruction aimed at the model (`swe-northwind-newgrad` and
  `product-manager-mid`). The expected output ignores it.

Run the extraction accuracy report against real models (opt-in, needs the models profile):

```powershell
$env:MODEL_PROFILE = "local"; $env:STRONG_EVAL_INPUTS = "1"
uv run pytest apps/worker/tests/test_extraction_accuracy.py -s
# or
uv run python -m strong_worker.inputs.accuracy --out inputs-accuracy.json
# only the CVs, with one line per case
uv run python -m strong_worker.inputs.accuracy --only resumes --cases
```

Every expected file must validate against its contract. A test checks this in CI.
