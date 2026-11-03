# RS02 · Resumes list on the shell

- **Branch:** `feat/rs-02-resumes-list`
- **Waits for:** RS01.
- **Owns:** `apps/web/src/pages/resumes/ResumesListPage.tsx`, its tests, and
  `apps/web/src/mocks/resumeHandlers.ts`.
- **Requirement IDs:** RSD-1, RSD-2, RSD-3, RSD-16.

## Goal

The list reads at a glance: three numbers per resume, with the actions in plain sight.

## Read first

- Spec RSD-1 to RSD-3, RSD-16, D-4 and D-10, and the mockup board "Resumes list (2 columns)".
- Today's `ResumesListPage.tsx`: `usedBy`, `deleteRolesNote`, `issueFacts`, the rename form and
  the delete dialog.

## Build

1. Replace the `sx-rows` list with a `sx-grid2` of `SummaryCard`s. Keep the page header, the intro,
   the "{n} of 5 · up to 1 MB each" line and the "resumes full" notice.
2. Tiles:
   - **roles**: a new `usingRoleCount(roles, resumeId)`, the count behind today's `usedBy`;
   - **open issues**: `resumeIssueCounts(resume).open`, tone `warn` when `.high > 0`;
   - **story ideas**: `ideas.length`.

   Use singular labels for 1. Use "—" while a count loads.
3. Meta: "Added {date} · {editedLabel}".
4. Footer:
   - Show details goes to `resumeCheckPath(id)`;
   - actions: **Set as default** (not on the default resume), **Rename** and **Delete**, each with
     a small stroke icon and `aria-label="{action} {name}"`.

   Remove the Open link, the "Open breakdown" link, the More menu and its outside-click code. Keep
   the inline rename form, which replaces the card body, and the delete dialog with
   `deleteRolesNote`.
5. A resume that is not extracted shows the card's loading state, the chip "Being read",
   "Strova is reading this resume. The numbers show when she is done." and only Rename and Delete.
6. While under `MAX_RESUMES`, an `AddCard` ("Add a resume", "{n} slots left. Add the version you
   sent for a role.") ends the grid and links to `START`.
7. RSD-16: if one request per card for story ideas stays, log it under Decisions. Do not add an
   endpoint.
8. Keep `usedBy` and `deleteRolesNote` exported; `usedBy` may lose its last caller. Delete
   `issueFacts` if nothing uses it.

## Done when

- The RSD-1, RSD-2, RSD-3 and RSD-16 tests pass, and the RM-1, RM-2 and RMAP-5 tests still pass.
- The screen check is done at 1280 and 390 for: default with high issues, a resume with no high
  issues, a resume being read, the rename form, the delete dialog, 5 of 5 (no AddCard), and empty.
