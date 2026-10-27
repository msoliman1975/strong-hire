# S35 · Recruiter screen

- **Branch:** `feat/v2-s35-recruiter-screen`
- **Wave:** 3. **Waits for:** C3.
- **Owns:** `prompts/planner/*recruiter_screen*`, `prompts/interviewer/*recruiter_screen*`,
  `prompts/scorer/*recruiter_screen*`, their fixtures, the recruiter screen option in the plan
  page's type picker (one entry in the type list), and the evals scenario for it.
- **Requirement IDs:** RS-1, RS-2.

## Goal

A fifth interview type: a short recruiter call that tests motivation, role fit, communication,
and logistics and expectations.

## Read first

- Spec: IV-2, IV-6, IV-7, "Competencies by interview type", and "Company profiles" (loop
  structure).
- How the planner and scorer pick prompts by interview type today.

## Build

1. Brief, question and rubric variants for `recruiter_screen`, as new prompt files selected by
   type, never by model. Questions cover motivation, the role and team, the candidate's
   background summary, and logistics (timeline, location, expectations), without asking for
   protected or salary-history information.
2. Default duration 30 minutes; Coach and Realistic modes work as for other types.
3. The type shows in the plan page setup and the Questions page filters.
4. A simulated-candidate scenario for the eval harness.

## Done when

Tests cover RS-1 and RS-2 on the fake model, plus a test that the prompts never ask about salary
history or protected characteristics.
