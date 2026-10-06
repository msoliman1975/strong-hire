# Prompts

LLM prompt templates, one folder per gateway role. Never put prompts inline in code.

- File name: `<name>.v<N>.txt`, for example `extractor/job_posting.v1.txt`. This is the default
  variant.
- Tier variant (PL-5): `<name>.<tier>.v<N>.txt`, where tier is `small`, `medium` or `large`, for
  example `scorer/rubric.small.v1.txt`. Small-tier prompts are shorter and ask for one thing at
  a time. Add a tier variant only when the default does not work for that tier.
- The loader reads the tier of the model that serves the role from the capability registry
  (`tier` in `config/models.<profile>.yaml`). If a file for that tier exists, it uses the tier
  variant. Otherwise it uses the default variant. `MODEL_PROFILE=fake` has no tier.
- Each variant has its own version numbers. The loader takes the highest version of the chosen
  variant. `rubric.small.v1` and `rubric.v3` can exist side by side.
- A file that starts with `<name>.` but breaks these rules (for example `rubric.tiny.v1.txt`)
  makes `load_prompt` raise `PromptFileNameError`.
- Never edit a version that has shipped. Copy it to `v<N+1>` and change the copy.
- Placeholders use `$name` (Python `string.Template`). No vendor-specific syntax.
- Load with `strong_core.prompts.load_prompt(role, name)`. The ref is recorded on the output,
  for example in `Scorecard.rubric_version` (PL-6). A default variant gives
  `extractor/job_posting.v1`. A tier variant adds the tier: `scorer/rubric.small.v1`.
- Every prompt change runs the eval harness in `evals/`.

`smoke/` holds the prompts for the gateway smoke test (`python -m strong_core.gateway.smoke`).
They are not a gateway role.
