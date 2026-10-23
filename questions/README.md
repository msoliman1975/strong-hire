# Question bank

The Questions page (QB-1 to QB-5 in `docs/spec.md`) lists two kinds of questions:

- **Company questions:** the `sample_questions` of each Published profile in `profiles/`.
- **General questions:** `general.json` in this folder, validated by
  `strong_core.schemas.GeneralQuestionBank` (`schemas/general_question_bank.schema.json`).

Every question carries `hints`: `looking_for`, `strong_signals` and `watch_outs`, one to four
short bullets each. Hints are our own guidance, never a model answer. For company questions they
are written from the `strong_answer` note.

`role_families` and `levels` say which job categories and levels a question fits. Leave a list
empty when the question fits all of them.

Rules for general questions:

- `id` is a stable slug. Never reuse an id for a different question.
- `competencies` (one to three) must belong to the question's `interview_type`.
- Write in our own words. No NDA-protected questions and no copied paid content.

The API loads `general.json` at startup, so a change ships with the next deploy.
