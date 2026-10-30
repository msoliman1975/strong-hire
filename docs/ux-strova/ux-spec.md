# Strong Hire UX with Strova: approved design

Approved by Mo Soliman on Oct 30, 2026, after six UX discovery rounds and a review of the
clickable mockups. This file and `reference/mockups.html` are the source of truth for the build.

- **Mockups (visual and copy):** `docs/ux-strova/reference/mockups.html`. Open it in a browser
  (or Playwright) as a file. Each screen is a hash route, for example
  `mockups.html#home`. The same file is published at
  https://claude.ai/artifact/85ETi6z82XtAKXmS4wQ7tn
- **Strova avatar (approved):** the `strova(mode, size)` function inside `mockups.html` is the
  approved drawing and animation. The design canvas page "Strova avatar (approved)" at
  https://claude.ai/artifact/KwPbVu6fzqAv3Kk4sGwv4J shows every mode and size.
- **Precedence when sources differ:** for layout, copy, colours and states, the mockups win. For
  behaviour, data and rules, this file wins. For anything neither covers, `docs/spec.md` and
  `CLAUDE.md` win. Sample data in the mockups (Ana, Stripe, Shopify, scores) is illustration
  only: the app shows the user's real data.

## 1. Principles

1. **Resume first.** The resume is the first thing a user gives us and the foundation of
   everything else: breakdown, issues, story ideas, and every rehearsal.
2. **One next step per screen.** Each screen has one primary button. Everything else is secondary.
3. **Ask only when needed.** No optional steps in the middle of a flow.
4. **One word per thing.** See the terminology table (section 3).
5. **Suggest, never overwrite.** Strova proposes changes as a before-and-after the user accepts.
   It uses only the user's own words (CO-9 applies to every suggestion).
6. **Every suggestion says why** and links to its source ("from your Stripe take, answer 1").
7. **Collapsed by default where lists get long,** with counts and status visible when collapsed.

## 2. Who it is for

The primary user is an **active job hunter**, applying to several roles, often arriving right
after a failed interview. The first session must leave them with **a clear plan and better
stories**. They use Strong Hire in bursts before interviews plus light ongoing story and resume
work in between.

## 3. Concepts and terminology

| Thing | What it is | UI word (use exactly) |
| --- | --- | --- |
| Resume | The user's CV, parsed. One is the **main resume**. Required before any rehearsal | "resume" everywhere. Never "CV" in user-facing copy |
| Target role | A real job posting the user is aiming at. The resume is chosen once per role (main resume by default) | "Target role" |
| Interview | Target role × Resume × Interview type, for example "Stripe · Behavioral". Has a readiness score | "interview" means one of these. The real-world event is "your interview" / "onsite" |
| Take | One run of an interview with Strova. Retake any time | "take", "Start the take", "Retake" |
| Story | The user's own story, five parts (context, stakes, your action, result, reflection), shared across roles, with a note per role | "story", "Career Stories" |
| Plan | One personal plan per user: stories, resume fixes and rehearsals | "Your plan" |
| Strova | The one AI agent. Coaches and plays the interviewer | "Strova" (see section 4) |
| Mode | Realistic (counts toward readiness) and Practice (pause, hint, redo; does not count) | "Realistic mode", "Practice mode". The stored enum value `coach` stays; only the label changes |

Statuses of a story: **Draft** (parts missing) → **Ready** (all five parts written) → **Proven**
(met the bar in a Realistic take, ST-7). Ready is derived, not stored.

## 4. Strova, the agent

### 4.1 One agent, two hats

Strova is the single AI character in the product. She guides the user everywhere (resume
analysis, story crafting and review, the plan, suggestions) and she plays the interviewer in
takes. The hat she wears is shown by colour:

| Hat | Colour | Where |
| --- | --- | --- |
| Coach | violet `#5332e6`, soft `#eeeafe` | Home next step, stories, crafting, review, suggestions, "Strova's coaching" in the debrief |
| Interviewer | teal `#0b6e8c`, soft `#e0f2f7` | Rehearsals, the live room, "Strova's verdict" in the debrief |
| Celebrating | green `#12775a`, soft `#e3f4ec` | A story becomes Proven, a story becomes Ready, an interview reaches its readiness goal |

Copy rules: Strova speaks in the first person ("I found 3 issues"). The interface refers to her in
the third person ("Strova found 3 issues"). In the live room the copy is exactly
**"Strova is acting as {interviewer title} at {company}"**. There is no separate persona name.
Interviewer title: the company profile's interviewer role for that round when the profile names
one, else by type: behavioral "Engineering Manager", hiring manager "Hiring Manager", technical Q&A
"Senior Engineer", case "Product Lead", recruiter screen "Recruiter", custom "Interviewer". In
generic mode use "a {title}" with no company.

### 4.2 The avatar

A woman shown head, shoulders and chest: side-swept short brown hair (`#6b4226`), oval face with
built-in ears (skin `#e8b996`, shade `#d6a37f`), brows the same colour as the hair, no cheek
blush, a dusty violet top (`#a99bdc`) with faint lapels, inside a coloured ring. Port the
`strova(mode, size)` function from `reference/mockups.html` exactly (paths, transforms, colours).

| Mode | Expression | Effect beside her | Ring | Animation |
| --- | --- | --- | --- | --- |
| listening | soft smile | sound waves at her ear | teal, plain | waves pulse in turn |
| speaking | mouth open | voice waves | teal, plain | mouth moves, waves pulse outward, ring pulses |
| interviewing | level brows, flat mouth | scorecard with a tick | teal, plain | tick draws itself on a loop |
| thinking | eyes up, raised brows | three thought dots | teal or violet by hat, **zigzag** | zigzag ring rotates, dots light in turn |
| analysing | eyes down | document and magnifier | violet, **zigzag** | zigzag ring rotates, magnifier scans |
| coaching | gentle closed smile | speech bubble with a spark | violet, plain | bubble bobs, spark twinkles |
| celebrating | gentle smile, raised brows | sparks and dots | green, plain | sparks twinkle, dots float up, ring pulses |

All modes blink every few seconds. Below 64 px the side effects are hidden (face and ring only).
With `prefers-reduced-motion: reduce` every animation stops and the tick shows fully drawn. Every
avatar has `role="img"` and an `aria-label` such as "Strova is thinking"; colour and motion are
never the only cue, so the state also appears as text where it matters (live room chip).

Thinking mode colour: thinking uses the teal hat in the live room and the violet hat when
crafting a story (pass the hat explicitly).

### 4.3 Where Strova appears (sizes)

Reading your resume 160 (analysing) · Resume ready 88 (coaching) · What first 72 (coaching) ·
Home next step 104 (coaching) · Rehearsals header 72 (interviewing) · Live room 160 (listening,
thinking, speaking from the real interviewer state) · Debrief verdict 72 (interviewing) · Debrief
coaching 72 (coaching) · Proven notice 72 (celebrating) · Crafting 72 (thinking, then celebrating
when Ready) · Review result 72 (analysing) · Section headers 24 to 28 · Nav item 18.

## 5. Navigation and app shell

Top bar: logo "Strong Hire" with "with Strova", the usage pill, and the profile button (initials)
that opens Profile. Left rail, exactly these five items in this order:

1. **Home**
2. **{First name}'s Resumes** (from `users.full_name`; "Your resumes" when there is no name)
3. **Target roles**
4. **Rehearsals with Strova** (with an 18 px interviewing Strova)
5. **Career Stories with Strova**

There is no separate "Ask Strova" nav button: Ask Strova lives on the Career Stories page. The
question bank and Progress are not in the v2 nav. Their routes keep working for old links.
On phones the rail becomes a horizontal scrolling strip.

## 6. Screens

Each screen lists its mockup route. Copy in the mockups is final unless it is sample data.

### 6.1 Onboarding (no app rail; top bar with the three steps Profile · Your resume · Plan style)

The existing profile step (AC-3) runs first. Then:

1. **Start with your resume** (`#start`). Drop zone for PDF or DOCX up to 1 MB, a paste box, and
   "No resume file? Paste your LinkedIn experience instead" (pasted text goes through the same
   resume reading, IN-7 still applies). Primary: **Read my resume**. Three small cards explain
   what you get: Resume breakdown, Resume issues, Story ideas.
2. **Strova is reading your resume** (`#reading`). Strova analysing at 160 px. Polls the existing
   resume extraction task; on success moves on by itself; on refusal (IN-7) shows the reason and a
   way back.
3. **Here is what your resume shows** (`#cv-ready`). Three **expandable cards, collapsed by
   default**: Breakdown (roles, achievements, skills), Resume issues (count and the issues), Story
   ideas (count and the ideas). Inside: Breakdown and Resume issues each link to **Open breakdown
   and issues**; Story ideas links to **Open Career Stories**. Below: "One more question, then
   you're in." Primary: **Continue**.
4. **Breakdown and issues** (`#resume-check`). One screen: the full breakdown (summary, roles with
   dates and achievements, skills, education) on the left, the issues on the right, each with its
   fix action and "Accept as it is" (IN-12 rules, accepted issues stored as today). Back link to
   the results; primary **Continue** to plan style.
5. **How do you like to work?** (`#plan-style`). Intro: "Strova keeps one plan for you. For now it
   covers completing your stories and fixing your resume findings." A box **What your plan covers
   now** with three tiles: Stories (complete your stories, starting with your N ideas), Resume (N
   findings to fix or accept), Rehearsals (dashed, "Not yet: mock interviews join your plan once
   you add a target role"). Two choices: **Weekly plan** (examples, reminders by app and email,
   email can be muted) and **Readiness checklist** (examples, no schedule, no reminders). Before
   any target role the examples show only story and resume items plus a dashed "Rehearsals · Added
   when you add a target role" line. Primary: **Use the weekly plan / Use the checklist**.
6. **What would you like to do first?** (`#what-first`). Strova coaching at 72 px, copy: "Your
   resume and your plan are ready, so you can start anywhere. There's no wrong first step: every
   path below feeds the others, and you can switch at any time from Home." Two choices: **I'm
   applying to a role** (to Add a target role) and **Build my stories** (to Craft with Strova on
   the strongest idea). Links: fix my resume first, go to Home.

A user with no resume who opens any app screen lands on Start with your resume. Rehearsals and
role plans require a resume; a role added without one waits for it.

### 6.2 Home (`#home`)

1. "Good morning, {first name}" (time-of-day greeting).
2. **Next step hero**: Strova coaching at 104 px, eyebrow "Strova · next step", one sentence from
   the PR-2 advice, one line why, primary **Start the take** (or the step's action) and a ghost
   link to the related role.
3. **Your plan** card (section 7), weekly or checklist.
4. **Four summary cards**, same size, each opens its page: {First name}'s Resumes (main resume
   name with "Main" chip, issues open, story ideas), Target roles (count, each with days left or
   "no date"), Rehearsals with Strova (count, best readiness, not started count), Career Stories
   with Strova (count, Proven · Ready · Draft, suggestions from Strova). No suggestion lists on
   Home: suggestions live on their pages.

### 6.3 Resumes

- **{First name}'s Resumes** (`#cvs`): list of resumes, the main one marked "Main", each with roles
  using it, issues open, story ideas. Primary **Add a resume**. The user can set another resume as
  main.
- **Resume page** (`#cv`): name, Main chip, roles using it, Upload a new version. Sections:
  **Story ideas from this resume** (each idea with likely skills and what it still needs, **Craft
  with Strova** and **Not a story**; an achievement already used by a story links to it),
  **Breakdown** with Edit, **Resume issues** with fix and accept actions, and **Strova suggests ·
  from your stories** (a better resume line as a before-and-after: Add to resume / Dismiss).

### 6.4 Target roles

- **Target roles** (`#roles`): one card per role with date chip, resume and match score, and one
  readiness bar per interview. Primary **Add a target role**.
- **Add a target role** (`#add-role`): three steps in one screen. 1 Job posting (link or text,
  IN-1, IN-6). 2 Check the role (company, title, level, optional interview date, must-have
  skills; profile notice when curated). 3 **Interviews Strova suggests** from the company's usual
  rounds (profile loop; standard loop in generic mode), as checkboxes the user keeps or removes,
  plus "Measured against: {main resume} · Use another resume". Primary **Create the role**.
- **Role page** (`#role`): back link, title, date chip, match, resume with change link. **Interviews
  for this role** as cards (readiness score, goal 75, bar, takes and last signal, Retake or Start a
  take). **What they'll look for** (skills, where they'll probe from GA-2, must-haves the resume
  never shows from IN-12 job mode, link to the resume). **Your stories for this role** (per tested
  skill: best story with Strong/Thin/Missing or Proven, the "For {company}" tailoring note, Craft it
  with Strova when missing). **Know anything about this interview?** dashed card for IN-4 context.

### 6.5 Rehearsals

- **Rehearsals with Strova** (`#rehearse`): Strova interviewing at 72 px, the recommended next take
  hero, then every interview across roles with readiness bar and Retake or Start.
- **Interview page** (`#interview`): role back link, "{type} interview", "Role × Resume × Type"
  line. **Readiness** card (score of 100, goal 75, change since last take, practice-estimate note;
  "Your readiness appears after your first Realistic take" when none). **Skill coverage** card
  (scores out of 4, informational). **Next take** hero: "Take N", one-line setup ("Realistic, 10
  minutes, warm tone. Focus: …"), "Strova will act as {title} at {company}", primary **Start the
  take** / **Start the first take** / **Retake**, and **Change settings** opening a drawer with
  difficulty, mode (Realistic, Practice, with the Practice explanation), tone (As {company}, Warm,
  Neutral, Direct), length (10, 30, 45; paywall rules unchanged). **Takes** list (each opens its
  debrief).
- **Live room** (`#live`): dark room as today. Strova at 160 px in the interviewer hat, mode driven
  by the real interviewer state (listening while the candidate speaks, thinking while the turn is
  computed, speaking while TTS plays), the chip "Strova is {state}", and "Strova is acting as
  {title} at {company}". Phases, question captions, answer length bar (LR-1), prep buttons
  (IV-11), End take. The mockup's "Preview her states" buttons are a review aid only; do not ship
  them.
- **Debrief** (`#debrief`): header with company · type · debrief, "Take N with Strova", back to the
  interview, transcript link (TR-1). **Strova's verdict** card (teal top border, interviewing
  avatar, "Wearing the interviewer hat: {title} at {company}"): hire signal with change (DB-1),
  answers met the bar (DB-2), readiness, rationale. **Answer by answer** (question, story used or
  why none, the fix, score of 4). Delivery metrics (DM-2) stay, below the answers. **Strova's
  coaching** card (violet top border, coaching avatar, "Back on your side: what to do next"): one
  coaching sentence, then suggestions (section 8): tune a story with a before-and-after (Apply,
  Edit first, Dismiss, then Undo), new story from a strong answer, missing skill, the Proven
  celebration (celebrating avatar), and "Your plan updated: next is …" with Back to Home.

### 6.6 Career Stories

- **Career Stories with Strova** (`#stories`): title, then **Start a new story** with two choices:
  **Craft with Strova** (Strova asks, you answer) and **Write it yourself** (write the five parts;
  Strova can review it). **Stories recommended from your resume** (collapsed by default, header
  shows "N ideas · M already a story"; each idea: Build on it, Dismiss). **Ask Strova** box (a
  question about your stories; the answer appears as a coaching card under the box). **Your
  stories** with skill coverage chips and the list (Proven, Ready, Draft). **Strova suggests**
  (collapsed by default, header shows the count).
- **Craft with Strova** (`#craft`): the coach session (CO-2 to CO-6) with a gentle/direct switch,
  chat on the left, "Taking shape" on the right with Strova thinking at 72 px (celebrating when the
  story becomes Ready) and the five parts filling in. Starting from a resume idea seeds the
  achievement as context, so the first question is about stakes. Starting from a missing skill
  sets the target skill.
- **Write it yourself** (`#write`): title and the five parts as text areas with hints, a note that
  Strova can review it, primary **Save and ask Strova to review**, secondary **Save as a Draft**.
- **Review with Strova** (`#review`): the story's parts on the left; on the right "Ask Strova to
  review" with what she checks, then after the review: what is good, each weak part with a
  before-and-after (Accept, Skip), and missing parts with a way to answer them with Strova.
- **Story page** (`#story`): title, status chip, Draft → Ready → Proven steps, skills; Practice a
  take (CO-7) and Review with Strova; any open suggestion; parts with 60-second and full versions
  (CO-8); **Used for** (roles and their tailoring notes); **Where it came from** (resume line,
  debrief answer or "Written by you") and takes.

### 6.7 Profile (`#profile`)

Plan style (same two choices, full examples including rehearsals), reminders (in the app: on;
by email: Mute email / Unmute), account summary. Billing, export and delete stay where they are.

## 7. The personal plan

One plan per user. It has three kinds of items, each with its own chip and colour:

| Kind | Chip | Items |
| --- | --- | --- |
| Rehearsals | teal "Rehearsal" | one per interview below its readiness goal of 75: "Stripe · Behavioral: readiness 75 or more" (now 58) |
| Story completion | violet "Story" | one per tested skill with no Ready story ("Conflict handling: a Ready story"); one per started Draft ("Get X to Ready"); resume ideas not yet built |
| Resume gaps and issues | amber "Resume" | one per open resume issue on the main resume |

- **Before any target role** the plan has only Story and Resume items (rehearsal items appear when
  a role is added).
- **Checklist style:** three groups, **collapsed by default**, each showing chip, title, "X of Y
  done", a progress bar and a one-line status with the next item ("Next: Stripe · Behavioral, 58
  of 75 · 1 in progress · 2 not started"). Expanded: items with a check, a sub-line and an action
  button; the next item is highlighted.
- **Weekly style:** "This week's plan", the week's dates, a legend of the three chips, then up to
  one item per day (Mon to Sat), each with its chip, done items struck through, today's item
  highlighted with the primary action. Items before an interview date come first; the week is
  recomputed from the current state.
- Done is computed, never ticked by hand: an interview at 75 or more, a story Ready or Proven, an
  issue fixed or accepted.
- **Reminders** (weekly style only): smart, sent by Strova when an item is due today or an
  interview is 3 days away with readiness below 75. In the app: the Home plan highlights today's
  item. By email: at most one a day, from "Strova from Strong Hire", respecting `product_email` and
  a new email mute for plan reminders.
- The style is chosen in onboarding and changed under Profile at any time; progress is kept.

## 8. Suggestions from Strova

One data model, shown where they belong, each with its source and a one-tap accept and dismiss.
Dismissed suggestions do not come back.

| Kind | Created when | Proposes | Shown on | Accept does |
| --- | --- | --- | --- | --- |
| Tune a story | A scored answer used a story (ST-6 already finds it) | A before-and-after edit of one part, only words from the answer | Debrief coaching, story page, Career Stories "Strova suggests" | Applies the edit; Undo restores |
| New story | An answer scores 4, or 3 with all parts present, and matches no story | A Draft or Ready story with parts filled from the answer | Debrief coaching | Saves the story |
| Missing skill | A tested skill has no story, or its answer scored 2 or less | Craft with Strova aimed at that skill and role | Debrief coaching, role page, Career Stories | Opens crafting with the target skill |
| Tailor for a role | Story fit runs for a role (ST-5) | Lead story per skill and one detail to bring forward | Role page, story page, Career Stories | Adds a "For {company}" note to the story |
| Improve resume line | A story has a result or number its source resume line lacks | A rewrite of that line from the story's words | Resume page | Updates the line; the resume check runs again |
| Story idea | A resume is read or changed: one per achievement not used by a story | A story seeded with that achievement, with likely skills and missing parts | Resume ready, resume page, Career Stories | Opens crafting with the achievement as context |
| Review | The user asks Strova to review a story | Per-part notes and before-and-after edits | Review screen | Applies each accepted edit |

Story ideas list every achievement without a model call; one worker call per resume adds the
likely skills (the list still shows when that call fails). Tune, new story, tailor, improve resume
line and review run through the gateway with new prompts and fake fixtures; the CO-9 eval suite is
extended to them.

## 9. Readiness per interview

- Score 0 to 100 per interview (role × resume × type), from **Realistic takes only**, labelled as a
  practice estimate (RD-3 notice wherever it shows). Goal 75.
- Formula: for each competency of the interview type, take its most recent rubric score from the
  last three Realistic takes of that interview; readiness = round((mean − 1) / 3 × 100) over the
  competencies scored so far. No Realistic take: no score ("–").
- Skill coverage shows the same per-competency scores out of 4, for information.
- The change since the previous take is shown on the interview page and the debrief.

## 10. Data changes (summary)

- `users.plan_style` (`weekly` | `checklist`, nullable until chosen) and
  `users.plan_email_muted` (bool, default false).
- `resumes.is_main` (bool; exactly one main per user among non-deleted resumes; the first resume
  becomes main).
- `target_interviews`: user-owned (org_id), job_target_id, resume_id, interview_type,
  created_at, archived_at. One row per interview the user keeps for a role.
- `suggestions`: user-owned (org_id, user_id), kind, status (open, accepted, dismissed), source
  (session_id, question_ref, resume_id, job_target_id), target story_id or resume_id, payload JSON
  (contract per kind), reason text, prompt_ref, created_at, resolved_at, and undo data for applied
  edits. In export and delete (AC-1).
- `takes` and stories: no change; story status Ready is derived.

## 11. What changes from the current v2 build

- The plan page (PP-1) is replaced by the **Role page** and the **Interview page**; its parts move:
  what they'll test and probe areas to the role page, story fit to the role page, earlier debriefs
  to the interview page's takes, setup to the interview page's next take and settings drawer,
  readiness to the interview page, the day plan (RD-2) to the personal plan's weekly style.
- Home v2, the story library page, the resume check page and the debrief v2 are reshaped as above.
- Coach mode is labelled Practice mode everywhere.
- The 3D avatar stays off (AV-1); Strova's 2D avatar takes its place in the live room.
- Question bank and Progress leave the v2 nav (routes kept).
- Everything stays behind `v2_enabled` (FL-1). v1 screens are untouched.
- Custom interviews (CU) stay available: "Add an interview type" on the role page offers Custom
  with the existing custom setup.

## 12. Requirement IDs

These IDs are the acceptance tests for this build. U00 writes them into `docs/spec.md` under a new
section "v2.1 UX with Strova".

**Navigation and terms**
- NV-1 The v2 nav has exactly: Home, {First name}'s Resumes, Target roles, Rehearsals with Strova, Career Stories with Strova.
- NV-2 User-facing copy says resume (never CV), take, Practice mode and Strova as in section 3.
- NV-3 Question bank and Progress are not in the v2 nav; their routes still work.

**Strova**
- SV-1 One `Strova` component renders the seven modes exactly as the approved drawing.
- SV-2 The ring colour shows the hat: violet coach, teal interviewer, green celebrating; zigzag ring when thinking or analysing.
- SV-3 Each mode animates as in section 4.2; all animation stops under reduced motion.
- SV-4 Every avatar has an accessible label naming the state.
- SV-5 Below 64 px the side effects are hidden.
- SV-6 The live room shows "Strova is acting as {title} at {company}" and a state chip, driven by the interviewer state.

**Onboarding**
- ON-1 After the profile, the only setup input is the resume: upload, paste, or pasted LinkedIn experience.
- ON-2 A reading screen with Strova analysing waits for the extraction and handles refusal.
- ON-3 The results screen shows Breakdown, Resume issues and Story ideas as collapsed expandable cards with links to the breakdown-and-issues screen and to Career Stories.
- ON-4 The breakdown-and-issues screen shows both on one screen with fix and accept actions.
- ON-5 The plan style screen explains what the plan covers now, marks rehearsals as added with a target role, and stores the choice.
- ON-6 The what-first screen offers the two paths with the "start anywhere" copy.

**Resumes**
- RM-1 The resumes page is titled with the user's first name and lists resumes with the main one marked.
- RM-2 One main resume per user; the first resume is main; the main resume is preselected for new roles.
- RM-3 The resume page shows story ideas, breakdown, issues and resume-line suggestions.
- RM-4 Story ideas list each achievement not used by a story, with likely skills, Craft with Strova and Not a story; dismissals persist.
- RM-5 The rule-based resume check runs in the API with the same results as the web check (shared fixtures).

**Target roles and interviews**
- TG-1 The target roles page shows each role with one readiness bar per interview.
- TG-2 Adding a role is three steps in one screen: posting, check, interviews.
- TG-3 Strova suggests interview types from the company's rounds; the user keeps or removes them; each kept type is a stored interview.
- TG-4 The role page shows the interviews, what they'll look for, stories for this role and the context card.
- RH-1 An interview is role × resume × type and is the unit for takes, readiness and the plan.
- RH-2 Readiness per interview follows section 9, from Realistic takes only, with goal 75.
- RH-3 The interview page shows readiness, skill coverage, the next take with a settings drawer, and the takes.
- RH-4 The rehearsals page lists every interview across roles and recommends the next take.
- RH-5 The mode labels are Realistic and Practice; the stored value is unchanged.

**Debrief**
- DB-3 The debrief opens with Strova's verdict in the interviewer hat.
- DB-4 Strova's coaching follows the answers, with the suggestions from this take.
- DB-5 A story that becomes Proven is celebrated with the celebrating avatar.
- DB-6 The debrief says what the plan's next item is now.

**Stories**
- ST-8 A story with all five parts is Ready; status shows as Draft, Ready or Proven.
- ST-9 The Career Stories page has, in order: start a new story, stories recommended from the resume (collapsed), Ask Strova, your stories, Strova suggests (collapsed).
- ST-10 Write it yourself saves a story and can send it to Review with Strova.
- ST-11 Review with Strova returns per-part notes and before-and-after edits from the user's words.
- ST-12 Crafting can start from a resume idea (seeded as context) or a missing skill (target skill).
- ST-13 Ask Strova answers a question about the user's stories and roles.
- ST-14 The story page shows status steps, parts and versions, used-for notes and its source.

**Suggestions**
- SG-1 Suggestions are one user-owned model with kind, status, source, target, payload and reason, in export and delete.
- SG-2 Tune a story from a debrief answer, applied with undo.
- SG-3 New story from a strong answer that matches no story.
- SG-4 Missing skill opens crafting for that skill and role.
- SG-5 Tailor for a role adds a "For {company}" note.
- SG-6 Improve a resume line from a story's words; the resume check runs again.
- SG-7 The no-new-facts eval covers tune, new story, review and improve resume line.
- SG-8 Every suggestion can be accepted or dismissed; dismissed ones do not return.

**Plan and Home**
- PS-1 One personal plan per user with rehearsal, story and resume items.
- PS-2 The plan style (weekly or checklist) is stored and can be changed in Profile.
- PS-3 Checklist groups are collapsed by default and show count, progress and next item.
- PS-4 The weekly plan shows up to one item per day with chips and today's item highlighted.
- PS-5 Before any target role the plan has only story and resume items.
- PS-6 Weekly-style reminders by email respect product_email and the plan email mute.
- HO-1 Home shows the greeting, Strova's next step, the plan and the four summary cards, and no suggestion lists.

## 13. Not in this build

Personalized and saved questions (hidden). Photo-real avatar. Native apps. Pricing changes.
Real job-outcome tracking (we track rehearsal progress only).
