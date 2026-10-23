# Strong Hire Custom Interview: Product & Technical Spec v1

Status: v1, agreed 2026-10-18. Decisions D-1 to D-15 below. Ships before the private beta (Nov 30).
This spec extends `docs/spec.md` (IV-2 interview types, the interviewer brief, FB-2, PR-1 to PR-3,
BL-1, BL-2, AC-1) and the Questions page (QB-1 to QB-5, PRs #78 to #81).

## Overview

"Personalize your interview questions." The candidate uploads a CV and a job description as today,
then builds the session: which kinds of question to practice, which topics to focus on, and their
own questions, for example the one a recruiter warned them about. The AI interviewer runs a normal
session around those choices and the scorer judges it with the standard rubric.

Custom is a fifth session type next to the four in IV-2. The four standard types do not change.
Everything new lives inside Custom, so it cannot change their scoring, rubrics or trends.

### Decisions

| ID | Decision |
| --- | --- |
| D-1 | Custom is a separate session type (`InterviewType.CUSTOM`), not an option on the four existing types. The word "mode" is not used for it: mode already means Coach or Realistic (IV-8). |
| D-2 | A Custom session mixes 1 to 3 question categories: Behavioral, Technical, Hiring manager, Case. Each has a time share, split evenly by default. |
| D-3 | Case needs a 45-minute session and allows at most one other category; a case needs about 20 minutes. |
| D-4 | Each category has focus chips (topics), pre-selected from the gap analysis probe areas and the job requirements. The candidate adds or removes chips. |
| D-5 | Own questions: up to 5 in a 30-minute session, 8 in a 45-minute session. The UI warns before the cap that not all may fit. |
| D-6 | Each own question has "Must ask" (on by default). Must-ask questions are scheduled first, and the session controller guarantees them, not the LLM. |
| D-7 | Questions are asked in the persona's voice with the meaning kept. An "Ask exactly as written" toggle asks the text word for word. |
| D-8 | The AI tags each own question with a category and competencies; the candidate can change the category. |
| D-9 | Own questions get the normal follow-up rules (IV-3, IV-4) and the normal rubric. The debrief marks them "Your question". |
| D-10 | Own questions are checked before the session: anything that is not an interview question, abuse, or instructions to the interviewer is refused with a reason (same pattern as IN-6, IN-7). Near-duplicates are flagged. |
| D-11 | Saved questions: a "My questions" list on the Questions page, and "Add to my interview" from any bank question. |
| D-12 | Realistic Custom sessions count toward PR-1 trends. Points that come from candidate-written questions are marked and can be filtered out. Coach sessions do not count (as today). |
| D-13 | Custom is a paid feature at launch, but open to every user while we test. A runtime setting switches it (`everyone` now, `paid_only` when live), with no deploy. While it is `everyone`, a free account may use one of its free interviews for a 30-minute Custom session (Custom has no mini, D-14); 45 minutes needs the plan. |
| D-14 | Custom is not offered as a 10-minute mini interview. |
| D-15 | "Run this setup again" (CU-9) always reuses the categories, focus chips and own questions, and always draws the interviewer's questions fresh. There is no keep-or-redraw toggle: keeping the interviewer's questions would need a core contract change (the setup has no place for planner questions). Instead, each interviewer question on the debrief has "Save to My questions", which saves it with its category and competencies; the candidate can add it to the next setup as an own question. Decided 2026-10-18 in C5. |

### Non-goals (v1)

- Mixing categories in the four standard types.
- Custom rubrics or competencies written by the candidate. Scoring uses the existing competency set.
- Sharing question sets between users, or importing a list from a file.
- Coding or whiteboard questions. Technical stays verbal (IV-2).
- Questions in a language other than the session language.

## User journey

1. On session setup the candidate picks **Custom** next to the four types.
2. **Categories:** picks 1 to 3. A slider sets the time share of each (defaults even; minimum 5
   minutes each; Case at least 20).
3. **Focus:** each category shows chips. Chips from the gap analysis probe areas and the job's
   must-have skills are pre-selected; the candidate edits them or types a new one.
4. **My questions:** the candidate types questions or adds saved ones. Each is checked and tagged
   as it is added (CU-5). Each shows its category, "Must ask" and "Ask exactly as written".
5. Difficulty, duration (30 or 45) and Coach or Realistic, as today.
6. A summary shows the plan: "About 7 questions: 3 of yours, 4 chosen by the interviewer from your
   focus areas." Then mic check and the session as in journey 2 of `docs/spec.md`.
7. **Debrief:** as today, with the per-question breakdown grouped by category and a "Your question"
   badge. Buttons: "Run this setup again" and "Save my questions"; each interviewer question has
   "Save to My questions" (D-15).

## Functional requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| CU-1 | Custom session type: 1 to 3 categories with time shares that add up to the core time. Case needs a 45-minute session and at most one other category. Not offered for the mini interview. | P0 |
| CU-2 | Focus chips per category, pre-selected from the gap analysis probe areas and the job's must-have skills; the candidate edits them. Free-text chips go through the CU-5 check. | P0 |
| CU-3 | Own questions: up to 5 (30 min) or 8 (45 min). Each is tagged with a category and 1 to 3 competencies from `COMPETENCIES_BY_TYPE` for that category; the candidate can change the category. | P0 |
| CU-4 | Must-ask questions are scheduled first and the session controller asks every one of them before CANDIDATE_QUESTIONS; it cuts probes on other questions to make room. "Ask exactly as written" makes the interviewer read the text unchanged. | P0 |
| CU-5 | Check each own question and free-text chip: refuse text that is not an interview question, abuse (IV-12 categories) or instructions to the interviewer, and show the reason. Flag a near-duplicate of another question in the session. | P0 |
| CU-6 | The scorer scores each question on its own competencies (it already does, `scorer.py` `_scored_competencies`). The debrief groups the breakdown by category and shows "Your question" on own questions. The hire signal uses the normal weights and hard rules. | P0 |
| CU-7 | Realistic Custom sessions count toward PR-1. Trend points from own questions are marked; a filter hides them. | P0 |
| CU-8 | "My questions": a saved list per user on the Questions page (add, edit, delete). "Add to my interview" from a saved or bank question. Saved questions are in the AC-1 export and delete. | P0 |
| CU-9 | "Run this setup again" from the debrief and from the rehearsals view (PR-3) reuses the categories, chips and own questions; the interviewer's questions are always drawn fresh (D-15). On the debrief each interviewer question has "Save to My questions", which saves it with its category and competencies (CU-8). | P1 |
| CU-10 | PR-2 can recommend a Custom session with chips filled from the open gaps ("Practice conflict handling and Kubernetes"): when scores under the bar span at least two interview types and the candidate has practiced every type the gaps point to. The setup mixes the gap types with the most points (at most 3, even shares, Case rules of D-3), up to 3 chips per category from the weakest competencies and the plan's focus topics, no own questions, 30 minutes (45 with Case). The standard advice stays next to it; it is not offered when Custom is locked (CU-11), and without 45-minute sessions Case is left out. | P1 |
| CU-11 | Runtime setting `custom_interview_access`: `everyone` (default) or `paid_only`. Under `paid_only` free users see Custom locked with an upgrade prompt; the free interview (BL-2) cannot be Custom. Custom uses plan minutes like any session (BL-1). | P0 |
| CU-12 | Company persona and values (IV-5) still apply. The planner fills the interviewer's questions from the focus chips and the company sample questions. Difficulty, seniority and Coach or Realistic work as in the other types. | P0 |

## Interviewer, planner and scoring

**Planner.** For a Custom session the planner gets the usual inputs plus the `CustomSessionSpec`.
It returns the normal `InterviewerBrief`:

- The candidate's questions are copied into `questions` with `source=candidate`. Their text is not
  rewritten in the brief; the interviewer adapts the wording live unless `verbatim` is set.
- The planner adds its own questions (`source=planner`) for the remaining time, spread over the
  categories by time share and drawn from the focus chips, the gap analysis and company sample
  questions.
- `target_competencies` is the union over the categories, capped at 6, ranked by the focus chips
  and the gap analysis.
- Must-ask questions get the top priorities. Within a category, own and planner questions are
  interleaved by priority so the session does not feel like two halves.

The planner never drops or changes a candidate question. If the candidate's questions alone overrun
the time, the API refuses the setup before the session (CU-3 caps make this rare).

**Session controller.** Moves through CORE category by category in the order the candidate set.
It tracks remaining must-ask questions; when time is short it lowers the probe limit on the other
questions and skips unasked planner questions first. The LLM still never decides when the session
ends.

**Validation (CU-5).** A new `extractor` call (`CustomQuestionCheck` output) runs when a question
is added: is it an interview question, which category and competencies, is it abuse or instructions
to the interviewer. Text that looks like instructions is refused, never forwarded. The planner
prompt also wraps candidate questions as quoted data, so a missed one cannot change the brief.

**Scoring.** No new rubric. Each question is scored on its own competencies, at the session's level
bar. The debrief groups by category. Own questions get the same scrutiny as planner questions: no
softer scoring because the candidate chose them.

## Data model changes

All in `packages/core` (one PR that merges first).

- `InterviewType.CUSTOM` in `schemas/enums.py`, and `STANDARD_INTERVIEW_TYPES` for the other
  four. Custom has no entry in `COMPETENCIES_BY_TYPE`; `session_competencies(config)` returns a
  session's pool (the union over a Custom session's categories).
- Question categories reuse the four standard `InterviewType` values through the `StandardType`
  annotation, which refuses `custom`. Company profiles and the gap analysis session plan use it
  too, so they can never name Custom.
- `QuestionSource` (`planner`, `candidate`) and `QuestionRefusal` (`not_a_question`,
  `inappropriate`, `instructions`) enums.
- New contracts in `schemas/custom.py`:
  - `CustomCategory`: `category`, `share` (0 to 1), `focus` (list of chip strings).
  - `CustomQuestion`: `text`, `category`, `competencies`, `must_ask`, `verbatim`,
    `saved_question_id` (optional).
  - `CustomSessionSpec`: `categories` (1 to 3), `questions` (0 to 8), with validators for D-3,
    shares and duplicates.
  - `CustomQuestionCheck`: `is_question`, `refusal`, `reason`, `category`, `competencies`.
- `SessionConfig.custom: CustomSessionSpec | None`, required when `interview_type` is `custom` and
  absent otherwise. `SessionConfig` checks the rules that need the duration: no mini, the CU-3
  caps, Case needs 45 minutes.
- `BriefQuestion` gains `source` (`planner` default, `candidate`), `category` (optional),
  `must_ask` (default false) and `verbatim` (default false). Defaults keep existing briefs valid.
  `BriefDraft` now holds `DraftQuestion`s (the old fields plus an optional `category`), so the
  planner model can never set `source`, `must_ask` or `verbatim`; only code does.
- New table `saved_questions`: `id`, `org_id` (FK `orgs`, non-null), `user_id`, `text`,
  `category`, `competencies`, `bank_ref` (optional, when added from the bank), timestamps. In
  `USER_OWNED_TABLES`; in the AC-1 export and delete.
- `sessions.custom_json` holds the `CustomSessionSpec` (NULL for the standard types).
- Runtime setting `custom_interview_access` in `strong_core/runtime_settings.py`, shown on the admin
  Controls page.
- `./scripts/dev.ps1 schemas` after the contract changes; fake fixtures for `CustomQuestionCheck`
  and a Custom `InterviewerBrief`.

## API surface (new or changed)

| Method and path | Purpose |
| --- | --- |
| `POST /sessions` | Accepts `interview_type=custom` with `custom`. Enforces CU-1, CU-3 and CU-11 (403 with `upgrade_required` under `paid_only`). |
| `POST /custom/questions/check` | Runs the CU-5 check on one question or chip; returns the tag or the refusal reason. Rate limited. |
| `GET /custom/focus?job_id=&resume_id=` | Suggested chips per category from the gap analysis and the job (CU-2). |
| `GET/POST/PATCH/DELETE /questions/mine` | Saved questions (CU-8). |
| `POST /sessions/{id}/repeat` | Builds a new setup from an earlier Custom session (CU-9). |
| `GET /sessions/{id}/debrief` | `questions[]` gains `competencies` (CU-9); `next_custom_session` is the CU-10 advice. |
| `GET /job-targets/{id}/progress` | Gains `next_custom_session`, a Custom setup to prefill, or null (CU-10). |
| `GET /status` | `SiteStatus` gains `custom_interview_access` so the web app can show the lock. |

## Delivery plan

| PR | Branch | Content | Depends on |
| --- | --- | --- | --- |
| C0 | `feat/c0-custom-core` | Enums, contracts, `BriefQuestion` fields, `saved_questions` migration, runtime setting, schemas, fixtures | none |
| C1 | `feat/c1-custom-worker` | Planner for Custom (CU-12), the CU-5 check, scorer and debrief grouping (CU-6), prompts in `prompts/planner/` and `prompts/extractor/` | C0 |
| C2 | `feat/c2-custom-api` | Endpoints above, gating (CU-11), saved questions in AC-1 export and delete, PR-1 marking (CU-7) | C0 |
| C3 | `feat/c3-custom-voice` | Session controller: category order, must-ask guarantee, verbatim, text mode (PL-7) | C0 |
| C4 | `feat/c4-custom-web` | Custom setup screen, My questions, debrief badges and grouping, trend filter, lock state | C2; the QB web PR (#81) for the Questions page |
| C5 | `feat/c5-custom-repeat` | CU-9 and CU-10 | C1, C2, C4 |

C1, C2 and C3 run in parallel after C0. The beta minimum is C0 to C4 (CU-1 to CU-8, CU-11, CU-12).
C5 (P1) lands before the beta if the launch-gap work (L00 to L11) is on track, else in December.

**Evals.** Add simulated-candidate runs (`docs/sim-candidate.md`) for: a mixed 3-category session,
a session that is all must-ask questions, and an injection attempt in an own question. Check that
every must-ask question is asked and that scores on own questions match the gold set's bar.

## Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Prompt injection through own questions | Interviewer leaves its role | CU-5 check, quoted data in prompts, IV-12 still applies live |
| Candidates pick easy questions | Inflated trends | Marked trend points and filter (CU-7); planner still adds questions from gaps |
| Too many categories in 30 minutes | Shallow coverage | Minimum share per category, Case rules (D-3), caps (D-5) |
| Must-ask questions crowd out probing | Weaker practice | Controller lowers probes on planner questions first; UI warning before the cap |

## Open questions

None for v1.
