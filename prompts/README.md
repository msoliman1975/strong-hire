# Prompts

LLM prompt templates, one folder per gateway role. Never put prompts inline in code.

- File name: `<name>.v<N>.txt`, for example `extractor/job_posting.v1.txt`.
- Never edit a version that has shipped. Copy it to `v<N+1>` and change the copy.
- Placeholders use `$name` (Python `string.Template`). No vendor-specific syntax.
- Load with `strong_core.prompts.load_prompt(role, name)`. The ref (`extractor/job_posting.v1`)
  is recorded on the output, for example in `Scorecard.rubric_version`.
- Every prompt change runs the eval harness in `evals/`.

`smoke/` holds the prompts for the gateway smoke test (`python -m strong_core.gateway.smoke`).
They are not a gateway role.
