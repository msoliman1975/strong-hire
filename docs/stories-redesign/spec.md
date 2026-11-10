# Career Stories redesign: spec

Status: **approved 2026-11-09.** Decisions D-1 to D-6 come from the owner's answers; D-7 and the
open questions were approved as proposed. Requirement IDs use the prefix `CS-`. The mockup is
`mockup.html` in this folder; open it in a browser.

It covers:

- the Career Stories page (`/stories`, `CareerStoriesPage.tsx`);
- the duplicate-recommendation bug across resume versions (CS-1 to CS-4);
- rename, archive and delete of a story (CS-12 to CS-17).

## Why

- **Stories are not the first thing on the page.** Today the page shows, in order: two big
  "start" cards, a folded "Recommended from your resume" card, Ask Strova, then "Your stories",
  then a folded "Strova suggests" card. The user's own stories sit in the middle.
- **The same idea shows up twice on one page.** A resume idea is in "Recommended from your
  resume" and again as a `story_idea` item in "Strova suggests".
- **The same idea comes back with every resume version.** Ideas are matched only against the
  suggestions of *that* resume, plus an exact-text check against story parts. A line that was
  dismissed, or turned into a story, from resume v1 is recommended again on v2, and a reworded
  line ("Cut infra cost by 30%" → "Reduced AWS spend 30% via rightsizing") is always new.
- **Job tailoring is hidden.** `tailor_role` tips sit in the folded "Strova suggests" card,
  away from the story they belong to.
- **No rename, archive or soft delete** on the list. Delete exists only in the API, and it is
  permanent.

## Decisions

- **D-1. One telling per story, no versions.** A story has one set of parts. Tailoring for a job
  stays a "For {company}: …" note (today's `tailor_role` accept). On the list, open tips show as
  company tags on the story's row: `Tips: Stripe (1) · Shopify (2)`.
- **D-2. One list, with filter chips.** Stories and recommendations are rows of one list.
  Chips: All · Drafts · Ready · Proven · Recommended · Archived. Default is All, which leaves out
  archived stories.
- **D-3. Recommendations are pooled across every resume, matched fuzzily.** One row per
  achievement, however many resumes it appears in.
- **D-4. Archive hides the story and takes it out of prep. Delete is soft for 30 days.**
- **D-5. Skill coverage and Ask Strova live in a compact bar above the list.** Coverage chips
  also filter the list. Ask Strova opens a side panel.
- **D-6. No job selector.** Per-job content shows as tags: tip counts per company on story rows,
  and per-job skill gaps as Recommended rows tagged with the company.
- **D-7 (my call, please check). Starting a recommendation opens the existing authoring
  screens**, prefilled: Craft with Strova goes to `/coach/new?resume=…&idea=…` (or
  `?skill=…&job=…` for a job gap), Write it yourself goes to `/stories/new` with the achievement
  in Result and the skills preselected. The recommended row disappears once a story is linked to
  it, and the new story shows as a Draft row.

## Page layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Career stories                             [Ask Strova] [+ New story ▾] │
│ The moments you'll tell in "tell me about a time…" questions.           │
│                                                                          │
│ Ownership ✓  Impact ✓  Collaboration ~  Conflict ✕  Failure ✕  Comms ✓   │  ← coverage, clickable
│ All 7 · Drafts 2 · Ready 2 · Proven 1 · Recommended 4 · Archived 1       │  ← filter chips
│ ──────────────────────────────────────────────────────────────────────── │
│ Payments migration        Ownership, Impact      Ready   Tips: Stripe 1 ⋯│
│ On-call rework            Collaboration · 3 of 5 Draft                  ⋯│
│ Hiring loop redesign      Conflict               Proven ✦               ⋯│
│ ┄ Cut infra cost 30%      From 2 resumes · Impact  Recommended [Start ▾] ✕│
│ ┄ Conflict story          For Stripe – PM          Recommended [Start ▾] ✕│
└──────────────────────────────────────────────────────────────────────────┘
```

`[+ New story ▾]` is a split button. The main part starts Craft with Strova; the caret opens:

- **Craft with Strova**: Strova asks, you answer. Talk or type.
- **Write it yourself**: write or paste the five parts; Strova can review it after.

Each recommended row has the same `[Start ▾]` split button, prefilled from that idea (D-7).

### Row anatomy

| Row | Left | Middle | Right |
| --- | --- | --- | --- |
| Story | Title (link to the story) | Skills · "3 of 5 parts" for drafts · "you wrote it" | Status chip · tip tags · `⋯` menu |
| Recommended | Dashed left border, achievement text | "From 2 resumes" or "For {company} – {role}" · skills | `Recommended` chip · `[Start ▾]` · `✕` dismiss |
| Archived | Muted title | Skills · "Archived {date}" | `⋯` menu (Unarchive, Delete) |

The `⋯` menu on a story: **Rename** (inline edit of the title, Enter saves, Esc cancels),
**Archive**, **Delete**. Expanding the tip tags (click `Tips: Stripe 1`) opens the tips under the
row, grouped by company, each with **Add to notes** and **Dismiss** (today's `tailor_role`
accept and dismiss). `tune_story` tips show the same way, under a "Tune" tag.

### Sort order (filter All)

1. Drafts that have open tips, newest first.
2. Other drafts, newest first.
3. Ready, then Proven, most recently updated first.
4. Recommended: job gaps first (tagged with a company), then resume ideas in resume order.

### Empty and edge states

- No stories and no recommendations: today's empty copy and a "Build my first story" button.
- No stories but recommendations: the recommended rows, with a one-line hint above them:
  "Strova found these in your resume. Start with one."
- A filter with no rows: "No {filter} stories." and a link back to All.
- After Delete: a toast "Deleted 'Payments migration'. Undo" for 10 seconds; the story is also
  listed under a "Recently deleted" link at the bottom of the Archived filter for 30 days.

## What goes away

- The two big "Start a new story" cards (replaced by the split button).
- The "Stories recommended from your resume" card (its rows join the list).
- The "Strova suggests" card. Its kinds move:
  - `story_idea` → Recommended rows (merged with resume ideas, so no duplicates);
  - `missing_skill` → Recommended rows tagged with the job;
  - `tailor_role`, `tune_story` → tip tags on the story's row.
- The "Already a story: …" lines. A used idea is simply not shown.

## Requirements

### Recommendations without duplicates (item 1)

- **CS-1.** Recommendations are pooled across every non-deleted resume of the user. An
  achievement appears at most once, however many resumes contain it.
- **CS-2.** Two achievements are the same idea when they are on the same role (same company,
  case-insensitive) and either their normalized text is equal, or the matcher says they describe
  the same work. The matcher runs in the worker, inside the existing `story_idea_skills` job, with
  the `extractor` role: it is given the new resume's lines and the user's existing ideas and
  stories for the same company, and returns matches. No match call runs when the normalized text
  is equal. The result is stored on the `story_idea` suggestion (`payload.same_as`: the id of the
  first suggestion for that idea), so the list endpoint stays rule-based.
- **CS-3.** An idea is not recommended when any resume's line for it was turned into a story,
  quoted in a story, or dismissed. Dismissing it once dismisses it for every resume.
- **CS-4.** A recommended row says how many resumes it came from ("From 2 resumes") and uses the
  text from the newest resume. Starting it links the new story to every suggestion of the idea.

### The list

- **CS-5.** One list holds the user's stories and the recommendations, in the order above. The
  page does not show a separate "recommended" or "suggests" card.
- **CS-6.** Filter chips: All, Drafts, Ready, Proven, Recommended, Archived, each with its count.
  All leaves out archived and deleted stories. The chosen filter is kept in the URL
  (`?show=recommended`).
- **CS-7.** Coverage chips sit above the filters. Clicking one filters the list to the stories
  and recommendations with that skill; clicking it again clears it. Coverage counts only
  non-archived stories (ST-9 rule otherwise unchanged).
- **CS-8.** `+ New story` is a split button: the main action is Craft with Strova, the menu has
  Craft with Strova and Write it yourself.
- **CS-9.** A recommended row has a `Start` split button with the same two choices, prefilled
  from the idea (D-7), and a Dismiss button.
- **CS-10.** A story row shows its open `tailor_role` and `tune_story` suggestions as tags per
  company ("Tips: Stripe 1"). Opening a tag lists the tips under the row with Add to notes and
  Dismiss.
- **CS-11.** A `missing_skill` suggestion shows as a Recommended row "{Skill} story", tagged
  "For {company} – {role}", whose Start opens crafting with that skill and job.

### Rename, archive, delete

- **CS-12.** Rename from the row menu edits the title in place. Empty titles are refused.
  Uses the existing `PATCH /stories/{id}`.
- **CS-13.** Archive sets `stories.archived_at`. Unarchive clears it. New endpoints
  `POST /stories/{id}/archive` and `POST /stories/{id}/unarchive`.
- **CS-14.** An archived story is left out of: skill coverage, story-fit for interviews (ST-5),
  Ask Strova answers (ST-13), the coach's story picks, and new suggestions. Its takes, scores and
  Proven status are kept.
- **CS-15.** Delete sets `stories.deleted_at` and hides the story everywhere. `DELETE
  /stories/{id}` becomes a soft delete; `POST /stories/{id}/restore` undoes it within 30 days.
- **CS-16.** A worker cron job hard-deletes stories whose `deleted_at` is older than 30 days,
  with their takes and notes (today's cascade).
- **CS-17.** Delete asks first: "Delete 'Payments migration'? You can undo this for 30 days."

## Data changes

One migration in `packages/core` (a small separate PR that merges first):

- `stories.archived_at TIMESTAMPTZ NULL`
- `stories.deleted_at TIMESTAMPTZ NULL`, with an index for the purge job.

No new table. `payload.same_as` lives in the existing JSON payload of `story_idea` suggestions
(the `StoryIdeaPayload` contract gains an optional field, so `schemas/` is regenerated).

`GET /stories` gains `?include=archived|deleted`. A new `GET /stories/recommendations` returns
the merged list for CS-1 to CS-4 and CS-11, so the page makes one call instead of reading the
main resume's ideas and the suggestions separately.

## Questions settled at approval

1. D-7: should the Recommended row stay visible (as "Started") until the draft is saved, or go
   as soon as crafting starts? The proposal says: go once a story is linked.
2. Should Write it yourself prefill Result with the achievement, or Context? The proposal says
   Result, since resume lines are mostly outcomes.
3. The Check your resume page (RSD-11) also lists story ideas for one resume. Should it use the
   pooled CS-1 rule too (so it hides ideas already dismissed on another version)? The proposal
   says yes.
