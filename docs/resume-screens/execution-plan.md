# Resume screens redesign: execution plan

One dedicated loop session builds RMAP-9, the resume screens redesign (`docs/resume-screens/spec.md`),
end to end and unattended, one task at a time. Each task is one branch and one PR into `main`,
merged by GitHub auto-merge with squash when CI is green. The loop driver is `prompts/LOOP.md`;
the rules for every task are `prompts/00-common.md`.

The build is web only (spec D-8): no `packages/core`, no migration, no API change.

## Tasks, in order

| ID | Task | Branch | Waits for | Main folders | Requirement IDs |
| --- | --- | --- | --- | --- | --- |
| RS00 | Spec and loop on main | `feat/rs-00-spec` | nothing | `docs/` | writes RSD-1 to RSD-16 into `docs/spec.md`, rewords RM-3 |
| RS01 | Shared card shell and stat tiles | `feat/rs-01-card-shell` | RS00 | `apps/web/src/components/ux/` | RSD-5 |
| RS02 | Resumes list on the shell | `feat/rs-02-resumes-list` | RS01 | `apps/web/src/pages/resumes/ResumesListPage.tsx`, mocks | RSD-1, RSD-2, RSD-3, RSD-16 |
| RS03 | Target roles on the shell | `feat/rs-03-roles-list` | RS01 | `apps/web/src/pages/roles/RolesPage.tsx`, `roles/shared.tsx` | RSD-4 |
| RS04 | Check page: header, steps, journey, findings | `feat/rs-04-check-steps` | RS01 | `apps/web/src/pages/onboarding/` (ResumeCheckV2 and new step files), `styles.css` (cvc) | RSD-7, RSD-8, RSD-9, RSD-10, RSD-13 |
| RS05 | Check page: stories, lines, drawers; retire the detail page | `feat/rs-05-check-absorb` | RS04 | `apps/web/src/pages/onboarding/`, `pages/resumes/`, `App.tsx`, links in `pages/` | RSD-6, RSD-11, RSD-12, RSD-14 |
| RS06 | Journey, accessibility, report | `feat/rs-06-e2e` | RS02, RS03, RS05 | `apps/web/e2e/`, tests | RSD-15; verifies all |

RS02, RS03 and RS04 touch different folders. Once RS01 has merged, any two of them may be open at
once. RS05 waits for RS04 because both change `ResumeCheckV2`.

## Done

The build is done when RS06 has merged and its report (the PR description) lists:

- every requirement ID RSD-1 to RSD-16, with the test that covers it;
- every screen and state checked, at 1280 and 390;
- every decision taken during the build.
