# Roadmap

Product items to build later. Each item has an ID (`RMAP-N`; `RM-` is taken by the Resumes
requirements in `docs/ux-strova/ux-spec.md`) so specs, execution plans and PRs can
refer to it. When an item gets requirement IDs in a spec, list them under Notes.

Fields: **Area** (api, worker, voice, web, core, prompts, infra), **Priority** (Now, Next, Later),
**Status** (Idea, Planned, In progress, Done).

| ID | Title | Area | Priority | Status |
| --- | --- | --- | --- | --- |
| RMAP-1 | Filter Rehearsals by target role | web | Next | Done |
| RMAP-2 | One resume list on the Resumes page | web | Next | Done |
| RMAP-3 | Clearer "Not checked yet" label on resumes | web | Next | Done |
| RMAP-4 | Call it the "default" resume, not the "main" one | web | Now | Done |
| RMAP-5 | Deleting a resume that a target role uses | web, api | Next | Idea |

## RMAP-1: Filter Rehearsals by target role

**Recorded:** 2026-11-02

**What:** On **Rehearsals with Strova** (`#rehearse`, `docs/ux-strova/ux-spec.md` section 6.5),
add a filter by job posting (target role). The default is **All**, which shows every interview
across roles, as the page does today. Picking one target role shows only that role's interviews.

**Why:** A user with several target roles sees one long list of interviews and can't easily focus
on the role they're preparing for next.

**Notes:**

- User-facing copy says "Target role", not "JD" (ux-spec section 3).
- Each interview already belongs to one target role (Target role × Resume × Type), so the list may
  be filterable on the client from data the page already loads. Check before adding an API change.
- Open questions: should the recommended next-take hero follow the filter? Should the filter be
  remembered between visits, or set from a role page link (for example `#rehearse?role=<id>`)?

**Done (2026-11-02):** a **Target role** dropdown on Rehearsals with Strova, shown when the user has
two or more roles: "All target roles (N)", then each role as "Company · Title (N)".

- The recommended next take follows the filter. With a role picked, it is worked out with the API's
  rule (`recommendNext`, the same as `recommend` in `strong_api/plan/interviews.py`). With All, it
  is the API's `next_interview_id`. If every interview of the role is at the readiness goal, a
  note says so.
- The filter is in the URL (`/rehearsals?role=<id>`), so Back, reload and shared links keep it, and
  a role page can link to it later. An unknown or archived role shows everything. No localStorage.
- Client-side only, from the data the page already loads. No API change.
- Also: when two roles share a company, their rows and the hero name the role title too, so
  "Rubrik · Behavioral" no longer appears twice with nothing to tell the rows apart.

## RMAP-2: One resume list on the Resumes page

**Recorded:** 2026-11-02

**What:** **{First name}'s Resumes** (`#cvs`, ux-spec section 6.3) shows the same resumes twice:

1. The main list: name, Main chip or **Make main**, roles using it, issues open, story ideas,
   **Open** (goes to the resume page).
2. **Rename or delete resumes ▾**, a collapsed **Saved resumes** list: name, date added, check
   status (to fix, accepted, high), **Open breakdown** (goes to `/resumes/<id>/check`),
   **Rename**, **Delete**.

Combine them into one list with one row per resume. Each row keeps the facts from both lists
(roles, issues, story ideas, date added, last checked) and has all the actions: Open, Open
breakdown, Make main, Rename, Delete. Rename and Delete can go in a row overflow menu so the row
stays light. Remove the collapsed "Saved resumes" section.

**Why:** Two lists of the same resumes with different actions make the user hunt for the right
one, and they say different things about the same resume.

**Notes:**

- The two lists disagree today. They count issues differently ("10 issues open" against "10 to
  fix · 0 accepted · 2 high"), and the second resume says "Not checked yet" but also "10 to fix".
  Check whether that is a bug and show one number in the combined row.
- "Used by Rubrik, Rubrik and Sourcegraph" repeats a company when two roles share one. Show role
  titles, or "Rubrik (2)".
- Code: `apps/web/src/pages/resumes/ResumesListPage.tsx` and
  `apps/web/src/components/LibrarySection.tsx` (the "Saved resumes" list, also used by other
  pages, so check those before changing it).
- Keep RM-1 and RM-2 in `docs/ux-strova/ux-spec.md` true: titled with the first name, main resume
  marked, one main per user.

**Done (2026-11-02):** one list, one row per resume. A row shows roles, issues (open, high,
accepted) and story ideas, then the date added and the check state. Its actions are Make main,
Open breakdown, Open, and Rename and Delete under **More**. Issue counts now come from the same rules
as the breakdown, so the page shows one number. "Used by" names a company once, with its role
count. "Not checked yet" was not a bug: it means the user has not confirmed the breakdown
(`confirmed_at`), while the issues are always found. It is now on its own line, apart from the
counts. The v1 Resumes page still uses `CvLibrary`, unchanged.

## RMAP-3: Clearer "Not checked yet" label on resumes

**Recorded:** 2026-11-02

**What:** A resume shows "Not checked yet" next to its issue counts, for example "Not checked yet ·
10 to fix". That reads as a contradiction: how can there be issues if it was never checked?

The issues are always found automatically, with the rules in
`apps/web/src/pages/onboarding/resumeChecks.ts`. "Checked Oct 28" only means the user saved the
resume from the breakdown page: `confirmed_at` is set by `PUT /resumes/{id}`. A user who opens the
breakdown and clicks **Continue** without editing still sees "Not checked yet".

Change the wording so it says what the user has done, for example "Reviewed Oct 28" and "Not
reviewed yet", or "Review the breakdown" as a link to it.

**Why:** The label makes users think the issue counts are wrong or stale.

**Notes:**

- The label comes from `checkedLabel()` in `apps/web/src/pages/onboarding/resumeSummary.ts`. It is
  shown on the Resumes page (RMAP-2), on the v1 "Saved CVs" list (`CvLibrary`), and in IN-12 tests.
  Check the Home card and the breakdown page for the same words.
- Decide too whether **Continue** on the breakdown should count as reviewed (set `confirmed_at`)
  even with no edit. That is an API change in `apps/api/src/strong_api/inputs/router.py`.
- Update the IN-12 tests that match "Checked Oct 28" and "Not checked yet".

**Done (2026-11-02):** the label now says what `confirmed_at` records: **"Edited Oct 28"** after the
user saves the resume from the editor, and nothing before that. "Checked" and "Not checked yet" are
gone from the v2 Resumes page. Open issues and **Open breakdown** already prompt a review.
`checkedLabel()` became `editedLabel()` in `resumeSummary.ts`. The v1 "Saved CVs" detail
("not checked yet") is unchanged, because v1 has a real confirm step.

**Not done:** **Continue** on the first-use breakdown does not mark the resume reviewed. The only way
to set `confirmed_at` is `PUT /resumes/{id}`, which also re-runs the story-idea skills job (a model
call) and every gap analysis that used the resume. That is too much for a click-through. If a
reviewed state is wanted later, add a light endpoint that only sets a `reviewed_at`.

## RMAP-4: Call it the "default" resume, not the "main" one

**Recorded:** 2026-11-02

**What:** Every user-facing "main" becomes "default":

- the **Default** chip on Resumes, Home and the resume comparison;
- **Make default**;
- **Default resume** on the resume page and the role cards;
- "Measured against: … (default)" on Add a target role;
- the delete dialog and the Resumes intro.

**Why:** "Default" says what it does: new target roles use it unless the user picks another.

**Done (2026-11-02):** copy only. The API keeps `is_main`, `POST /resumes/{id}/main` and the RM-2
requirement wording, the same way the stored mode `coach` kept its name when the label became
Practice. The terminology table in `docs/ux-strova/ux-spec.md` now says "default resume". A test in
`nv2Terms.test.tsx` fails if a v2 screen says "main" again.

## RMAP-5: Deleting a resume that a target role uses

**Recorded:** 2026-11-02

**Today:** Delete is allowed with no warning (`DELETE /resumes/{id}`, R1). The resume's text and file
go. The roles that used it keep their interviews, takes and gap report, and the report shows the
resume as deleted. The interviews still point at the deleted resume, so the role page has no resume
name. New takes keep running on the old gap analysis, because `_session_resume` in
`strong_api/sessions/router.py` does not check `deleted_at`. The only way to move a role to another
resume is **Compare my resumes**, then **Use this one** (RC-6), which needs two or more resumes.

**What:**

1. The delete dialog says which roles use the resume ("Used by Rubrik (2 roles)") and what
   happens to them.
2. Choose one of:
   - (a) offer to move those roles to the default resume first, with RC-6's move (archive the old
     interviews, copy the analysis);
   - (b) block the delete until no role uses it;
   - (c) delete, then flag the roles ("Pick a resume for this role").
3. Decide whether a take may start on an interview whose resume is deleted.

**Open question:** which of (a), (b) and (c). (a) keeps the user moving and fits "default".

