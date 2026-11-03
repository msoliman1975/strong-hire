# Resume screens redesign: spec (RMAP-9)

The owner approved this design on 2026-11-03. It covers three screens:

- the Resumes list (`/resumes`);
- the Target roles list (`/roles`);
- Check your resume (`/resumes/:id/check`), which absorbs the resume detail page
  (`/resumes/:id`).

The approved mockups are on the design canvas
<https://claude.ai/artifact/Hi9y2agVNadm9cmKLwhmWt>. Three boards are approved:

- "Resumes list (2 columns)";
- "Target roles (shared card shell)";
- "Check C2: Guided, revised (v2)".

Boards A, B and C on that canvas are rejected alternatives: do not build from them. Copies of the
three approved boards are in `docs/resume-screens/mockups/` (Design Component HTML; open them on
the canvas, not in a browser).

## Why

- **Two screens did the same job.** "Open" (`ResumeDetailPage`) and "Open breakdown"
  (`ResumeCheckV2`) both showed the resume and its issues. The check page is kept. The detail page
  is retired, and the five things only it had move to the check page (gap report below).
- **The list row was hard to read.** For example: "Used by Hussh, Twilio, Google, Anthropic,
  Rubrik (2 roles) and Sourcegraph · 4 issues open · 6 accepted · 18 story ideas". It becomes
  three numbers.
- **Rename and Delete were hidden** in a More menu.
- **The check page was one long scroll.** Editing, issues and checks were all on it, with no order
  of work.

## Gap report: what only the detail page had

| # | Function | Where it goes | Spec |
| --- | --- | --- | --- |
| 1 | Default chip and "Make this my default resume" | Check header (RS-7) | RM-2 |
| 2 | "Used by" roles with links | Check header link and the roles drawer (RS-7, RS-14) | RMAP-5 |
| 3 | Upload a new version | Check header (RS-7) | — |
| 4 | Story ideas: Craft with Strova, Not a story, already a story | Step 3 (RS-11) | RM-3, RM-4 |
| 5 | Resume-line rewrites from stories: Add, Undo, Dismiss | Step 4 (RS-12) | RM-3, SG-6 |

RM-3 changes from "the resume page shows ..." to "the check page shows ...". Its tests move with it
(RS-6).

## Decisions

- **D-1.** The check page is the only resume page. `/resumes/:id` redirects to
  `/resumes/:id/check` and keeps the query string. Links in the web app and in the API
  (`plan/personal.py`, `action_target`) keep working through the redirect. Web links are updated
  to the check path directly.
- **D-2.** Cards on both list pages are not links. **Show details** is the only way in, so the
  footer buttons never sit inside a link. The stat tiles are not interactive.
- **D-3.** Both list pages share one card shell:
  - a header with the title and a chip;
  - a row of three stat tiles;
  - a muted meta line;
  - optional body content;
  - a footer with Show details on the left and the actions on the right.

  It is one component in `apps/web/src/components/ux/`.
- **D-4.** The stat counts use today's rules, so the list and the check page always agree:
  - open issues: `resumeIssueCounts` (IN-12);
  - roles: active roles with an interview that uses this resume, the rule of today's `usedBy`;
  - story ideas: the `story-ideas` endpoint, open ideas only.
- **D-5.** There is no readiness score or bar on the check page. The step counts carry the
  progress.
- **D-6.** The check page is a guided page with four steps. The steps are views, not a wizard: the
  user can open any step at any time. The selected step is in the URL (`?step=`).
- **D-7.** Findings keep the client-side rule-based check (`resumeChecks.ts`, RM-5 parity). Nothing
  new runs on the server.
- **D-8.** No backend change. Every number and drawer comes from endpoints that exist:
  - resumes, issues and story ideas;
  - roles (`rolesApi.list`), jobs (`match_score`) and role `days_left`;
  - suggestions (`improve_resume_line`, with `story_id`) and stories, for the story title.
- **D-9.** Onboarding mode (the page opened with a `jobId` during setup) keeps today's Steps header
  and "Continue to your interview plan". It shows steps 1 and 2 only, opens on step 1 and lists
  the job's must-have skill findings. Steps 3 and 4 show when the user comes back from Resumes.
- **D-10.** Words: "Strova's findings" (not "issues") on the check page. The list tile still says
  "open issues", to match the existing IN-12 copy, so the counts line up visibly. Use resume,
  never CV. Sentence case everywhere.

## Requirements

Status: all P0 unless marked.

| ID | Requirement |
| --- | --- |
| RS-1 | The Resumes list shows one card per resume in two columns, and one column below 760 px. Each card shows the name, the Default chip on the default resume, three stat tiles (roles using it, open issues, story ideas) and "Added {date} · Edited {date}". The tiles are not interactive. The page no longer names the companies that use a resume. |
| RS-2 | The open issues tile turns amber, with a ▲ mark and the spoken label "Includes high-severity issues", when at least one open issue is high. It has no sub-text. Singular labels are used for 1 ("role"). |
| RS-3 | The card footer has **Show details** (to the check page) and, on the right, **Set as default** (only on a resume that is not the default), **Rename** (inline, as today) and **Delete** (today's dialog with the RMAP-5 roles note). There is no Open button and no More menu. A resume still being read shows empty tiles, "Strova is reading this resume" and only Rename and Delete. While under `MAX_RESUMES`, a dashed "Add a resume" card ends the grid. |
| RS-4 | The Target roles cards use the same shell: the role title and today's date chip; tiles for match, interviews and days left ("—" when unknown); the resume line; the readiness bars (TG-1); and a footer with Show details. "Pick a resume for this role" stays. The card is not a link. |
| RS-5 | The shared card shell is one component, used by both pages, with tokens from `theme/tokens.css` and no new colours. |
| RS-6 | `/resumes/:id` redirects to `/resumes/:id/check` with its query. `ResumeDetailPage` is removed and its tests move to the check page (RM-3, RM-4, SG-6 keep coverage). Every web link to a resume points to the check path. |
| RS-7 | The check page header shows the resume name, then the Default chip or a **Set as default** button. Under it: "Added {date} · Last saved {date} · Used by N roles". The roles link opens the roles drawer and is hidden at 0. Actions: **Upload a new version** and today's primary action (Use for an interview, or Continue to your interview plan in onboarding). |
| RS-8 | A step list sits beside the step view at 1280 and above it below 900 px. Each step shows its name, a count and one line. There is no readiness bar. The steps are: <br>1. **Your career journey**: "{n} roles · {y} years · {a} achievements". <br>2. **Strova's findings**: "and the fixes she recommends · {h} high", count of open findings. <br>3. **Stories to tell in interviews**: tag "Resume → Interview", count of open ideas. <br>4. **Stronger resume lines**: tag "Your stories → Resume", count of rewrites. <br>The step is in `?step=journey\|findings\|stories\|lines`. Without it the page opens on findings when one is open, else on journey (D-9 for onboarding). The current step has `aria-current="step"`. |
| RS-9 | Step 1 is the editable resume drawn as a timeline, newest first. It keeps all of today's editing: summary; roles add, edit, remove and reorder; moving an achievement; skills; education; certifications; Save. A gap over 3 months shows as a dashed amber segment and a link "{n}-month gap · {from} to {to} · see the fix" that opens that finding in step 2. A role with findings shows a "{n} finding(s)" chip. |
| RS-10 | Step 2 shows one finding at a time: "Finding {i} of {n} · {severity}", previous and next, the title, the detail, and a **Strova recommends** box with the fix in place. Date findings show the date fields of the roles involved; achievement findings show that achievement's field; skills findings show "Add {skills}". It keeps every accept reason (IN-12), the gap practice link and Save. "Next findings" lists the rest. Each one opens on click. Fixing or accepting moves to the next finding. |
| RS-11 | Step 3 shows one story idea at a time, with its skills, "Still needs: ...", **Craft with Strova** and **Not a story** (persists, RM-4). Under it: "Already crafted · {n}", linking each story. |
| RS-12 | Step 4 shows one resume-line rewrite at a time, with the source story's title, the before and after diff, and **Add to resume** (then Undo) and **Dismiss** (SG-6). With none, it says "No rewrites yet. Strova suggests one when a story has a result your resume leaves out." |
| RS-13 | On steps 2 to 4, a compact career strip sits under the step view: roles as segments sized by duration, gaps hatched in amber, and the role of the current finding outlined. "Open and edit" goes to step 1. It is drawn with `role="img"` and a spoken summary. |
| RS-14 | Three drawers open from the step list's footer links and the header: <br>• **Used by {n} roles**: company, title and stage chip for each role, with Open, plus "Add a target role with this resume". <br>• **Findings you accepted · {n}**: each with its reason and Undo. <br>• **What Strova checks**: today's list. <br>A drawer is a modal dialog from the right, at most 460 px and full width on phones. It traps focus, closes on Esc and on the backdrop, and returns focus to its opener. |
| RS-15 | All three screens pass axe with no violations and have no horizontal scroll at 390 px. |
| RS-16 (P1) | The open-issues and story-ideas counts on the Resumes list load without one request per card for story ideas. A batched read is allowed only if it needs no backend change; otherwise this stays as it is today and is logged. |
