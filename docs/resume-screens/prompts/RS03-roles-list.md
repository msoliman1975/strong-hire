# RS03 · Target roles on the shell

- **Branch:** `feat/rs-03-roles-list`
- **Waits for:** RS01.
- **Owns:** `apps/web/src/pages/roles/RolesPage.tsx`, `roles/shared.tsx` (helpers only) and the
  roles list tests.
- **Requirement IDs:** RS-4.

## Goal

Target roles and Resumes share one card look, and the role card shows its key numbers.

## Read first

- Spec RS-4 and D-2, and the mockup board "Target roles (shared card shell)".
- Today's `RolesPage.tsx`, plus `dateChip`, `ReadinessRow`, `resumeLabel` and `resumeGone` in
  `shared.tsx`.

## Build

1. Each role is a `SummaryCard`:
   - the title is `roleTitle(role)` and the chip is today's `dateChip` (teal when soon);
   - tiles: **match** (`job.match_score`, or "—"), **interviews** (`interviews.length`) and
     **days left** (`role.days_left` when it is 0 or more, tone `teal`; otherwise "—");
   - meta: `resumeLabel(...)`;
   - body: the `ReadinessRow` list or "No interviews kept yet.", and the "Pick a resume for this
     role" chip when `resumeGone`;
   - footer: Show details goes to `rolePath(role.id)`.

   The card is no longer a `<Link>`.
2. End the grid with an `AddCard`: "Add a target role", "Paste a job posting and Strova suggests
   the interviews."
3. Keep the empty state.

## Done when

- The RS-4 test passes, and TG-1 and the RMAP-5 roles tests still pass.
- The screen check is done at 1280 and 390 for: a role with a date soon, no date, no match yet,
  no interviews, a deleted resume, and no roles.
