# Strong Hire Deep Story Crafting: Product & Technical Spec v1

Status: draft for review, 2026-11-02. Roadmap items RMAP-8, with RMAP-7 folded in.
Decisions D-1 to D-14 below were taken with the owner one question at a time.
This spec extends `docs/spec.md`: stories (ST-1 to ST-14), the coach (CO-1 to CO-9) and
suggestions (SG-1 to SG-8). It also extends the v2 screens in `docs/ux-strova/ux-spec.md`
(Career Stories and the crafting session).

## Overview

Today Strova builds every story in one fixed shape of five free-text parts: context, stakes,
action, result, reflection. Each part is one or two sentences. Code decides the next question from
six shallow checks (`strong_api/coach/engine.py`, `asks()`):

1. a specific time;
2. the stakes;
3. "I", not "we";
4. a number in the result;
5. a trade-off word;
6. a reflection.

Context only has to exist. Nothing checks that the parts connect, and the output is five short
blocks.

This project makes crafting deeper and the result organized:

- two writing styles, STAR and CARL;
- named slots inside each section, with the empty ones visible;
- section-by-section questioning that digs into context;
- an advisory check that the story flows;
- skill hints at the end;
- inline editing and "Improve with Strova" per section;
- a roomier, formatted writing surface (RMAP-7).

Two principles from today stay unchanged:

- **The candidate owns the story.** Strova never adds a fact, a number, a name or a result
  (CO-9). It may now reword for clarity (D-6).
- **Nothing downstream breaks.** The interviewer, the scorer, story fit, debrief notes,
  suggestions and versions keep reading the five legacy text columns. Code fills those columns
  from the new outline on every save (D-12).

### Decisions

| ID | Decision |
| --- | --- |
| D-1 | Two styles. **STAR** = Situation, Task, Action, Result, Learning. **CARL** = Challenge, Action, Result, Learning. "STAR" in the UI means STAR plus Learning, which keeps today's reflection. |
| D-2 | The style is picked when a story starts. Strova suggests one from the target skill (rule in code, below). **Switch to STAR/CARL** later re-shapes the same facts into the other sections with one model call and no new facts. Existing stories have no style until they are organized (D-11). |
| D-3 | The story is an **outline of sections with named slots** (table below). Strova shows which slots are empty. The outline is the source of truth; the five legacy columns are derived from it (D-12). |
| D-4 | **Ready** needs only the core slots: your role, the problem, at least one action step with what you did and why, one result metric, and the lesson. The other slots are optional and never block Ready. |
| D-5 | **Context depth.** Strova asks for every context slot (company and team, your role, scale, timeframe, the problem and why it was hard, stakeholders) and presses once on each that is empty. "I can't share that" or "skip" marks the slot skipped, so it is not asked again. |
| D-6 | **Rephrase, no new facts.** Strova may reword a slot for clarity and interview tone. Every fact, number, name and claim must come from the candidate, and each Strova-written slot has verbatim `quotes`. CO-9 and its eval change from checking wording to checking facts (SC-15). |
| D-7 | **Pacing: section by section.** Each section opens with one open question that can fill several slots. Strova then follows up once per required or context slot that is still empty. The candidate can say "skip" (this slot) or "move on" (this section) at any time. |
| D-8 | **Skill hints, no probing.** Strova does not chase other skills during crafting. When the core slots are filled, it lists up to three "This story could also show {skill}" hints, gaps of the user's target roles first. **Deepen** opens a short section for that skill; **Not now** dismisses the hint. |
| D-9 | **Flow check, advisory.** One model call checks that the story hangs together (types below). Flags show on the story page and in the session. Each flag offers **Ask me about it**, which opens a short section chat, or **Dismiss**. The status never depends on it. |
| D-10 | **Editing.** Every slot can be edited inline; the user's own text needs no quotes. Each section has **Improve with Strova** with an optional note. It returns a before-and-after edit from the user's words to accept or reject, or questions when facts are missing. Whole-story **Review with Strova** (ST-11) stays and works on sections. |
| D-11 | **Existing stories** open in a classic view with **Organize with Strova**. One model call sorts the user's words into STAR slots with no new facts; the user previews it, then accepts or discards. Nothing is converted until someone clicks. |
| D-12 | **Legacy columns are derived.** On every outline save, a deterministic renderer in code (no model) writes `context`, `stakes`, `action`, `result` and `reflection` as plain text with Markdown stripped. All readers keep working. |
| D-13 | **Text first.** Text sessions get the full flow. Voice sessions (CO-6) use the same engine and slots with a lighter flow (fewer follow-ups, no flow check during the call) until a later release tunes it for speech. |
| D-14 | **RMAP-7 folded in.** The session screen gets a wide layout and a reply box that grows with the text, with an **Expand** button. The reply box and slot editors support light Markdown: bold, italic, bullet and numbered lists. Formatting is stripped wherever text goes to speech, scoring, word counts or verbatim quotes. |

## Sections and slots

`*` = required for Ready (D-4). `c` = context slot that Strova presses for (D-5). Slot keys are
stable API names.

| Section (STAR / CARL) | Slot key | Label | Rule |
| --- | --- | --- | --- |
| Situation / Challenge | `org` | Company and team | c |
| | `role` | Your role at the time | `*` c |
| | `scale` | Scale (users, money, systems, team size) | c |
| | `timeframe` | When, and how long | c |
| | `problem` | The problem, and why it was hard | `*` c |
| | `constraints` | Constraints (deadline, budget, people, tech) | |
| | `stakeholders` | Stakeholders, and what each wanted | c |
| Task (STAR only; in CARL these slots join Challenge) | `goal` | Your goal or responsibility | |
| | `success` | What success looked like | |
| | `assigned_by` | Who gave it to you | |
| Action | `steps[]` | 1 to 5 steps. Each step has `did` (what you did, `*` for at least one) and `why` (the decision, `*` for at least one), and optionally `alternatives` and `people` (how you brought people along) | `*` |
| Result | `metric` | A metric, before and after (`before`, `after`, `unit` and `text`) | `*` |
| | `impact` | Business or customer impact | |
| | `evidence` | How you knew it worked | |
| | `recognition` | Recognition | |
| Learning | `lesson` | The lesson | `*` |
| | `differently` | What you'd do differently | |
| | `since` | Where you've used it since | |

In CARL, `goal`, `success` and `assigned_by` are shown inside Challenge. That way switching styles
moves no fact and loses none. **Switch style** only renames sections and reorders slots,
unless the user asks Strova to rewrite the wording (one model call, D-2).

**Style suggestion (code, no model).** Strova suggests CARL when the target skill is one of
`conflict_handling`, `learning_from_failure`, `ownership`, `judgment` or `problem_framing`, or
when crafting starts from a "tell me about a challenge" question. Otherwise it suggests STAR.

## Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| SC-1 | A story has a style: `star`, `carl`, or none for a classic story. The start screen offers STAR and CARL with Strova's suggestion preselected (D-2). | P0 |
| SC-2 | A styled story stores an outline: sections with the slots above. Each slot holds `text`, `quotes` (Strova-written) or `by_user: true` (typed by the user), and a status: `filled`, `empty` or `skipped`. | P0 |
| SC-3 | Status: Ready when every `*` slot is filled (D-4). Draft otherwise. Proven is unchanged (ST-7). | P0 |
| SC-4 | The session works section by section (D-7). The engine, in code, picks the section and the empty slots to ask about. The prompt gets only those slots, so it never asks out of order. | P0 |
| SC-5 | Strova presses once on each empty context slot. "skip" or "I can't share that" marks that slot skipped; "move on" ends the section. A skipped slot is not asked again in that session (D-5). | P0 |
| SC-6 | Each Strova turn returns slot updates with text and verbatim quotes. It may reword, and adds no fact (D-6). | P0 |
| SC-7 | The session screen shows the outline live, with each slot filled, empty or skipped, and the section in progress. | P0 |
| SC-8 | When the core slots are filled, Strova offers up to three skill hints, gap skills of the user's target roles first, with **Deepen** and **Not now** (D-8). | P1 |
| SC-9 | Flow check (D-9). It runs once the core slots are filled, after a session, and with Review. It returns flags of these types: `action_vs_problem` (the actions don't address the stated problem), `result_vs_problem` (the result doesn't answer it), `number_conflict`, `timeline_conflict`, `loose_end` (a stakeholder or constraint named once and never closed). Flags are advisory and can be asked about or dismissed. A dismissed flag does not return until the slots it cites change. | P0 |
| SC-10 | Every slot is editable inline on the story page and in the session panel (D-10). | P0 |
| SC-11 | **Improve with Strova** per section, with an optional note. The result is a before-and-after edit with quotes to accept or reject, or questions that open a chat on that section. | P0 |
| SC-12 | **Switch to STAR/CARL** keeps every fact. It renames and reorders by default; **Rewrite the wording** is optional and costs one model call (D-2). | P1 |
| SC-13 | Classic stories show **Organize with Strova**: one model call, a preview, then accept or discard (D-11). | P0 |
| SC-14 | Code renders the legacy five columns from the outline on every save (D-12). The interviewer, scorer, story fit, debrief, suggestions and versions read the same columns as today. A test checks the mapping. | P0 |
| SC-15 | The no-new-facts eval (CO-9, SG-7) checks facts, not wording, on crafting turns, Improve, Organize and Switch. Every number, proper noun, tool and result claim in Strova's text must appear in the user's words. | P0 |
| SC-16 | Voice sessions fill the same slots with a lighter flow (D-13). | P1 |
| SC-17 | The session screen has a wide layout and a reply box that grows with the text, with **Expand** (RMAP-7). | P0 |
| SC-18 | The reply box and slot editors support bold, italic, bullet and numbered lists (Markdown, toolbar, Ctrl+B and Ctrl+I). Formatting is stripped for voice, scoring, word counts and quotes (RMAP-7). | P1 |

### Legacy column mapping (SC-14)

| Legacy column | Rendered from |
| --- | --- |
| `context` | Situation/Challenge: `org`, `role`, `scale`, `timeframe`, `constraints`, `stakeholders` |
| `stakes` | `problem`, then Task (`goal`, `success`) |
| `action` | `steps[]` in order, each as "did, because why" |
| `result` | `metric`, `impact`, `evidence` |
| `reflection` | `lesson`, `differently`, `since` |

## Technical design

### Core (`packages/core`, its own PR first)

- **Enums:** `StoryStyle` (`star`, `carl`); `StorySection` (`situation`, `challenge`, `task`,
  `action`, `result`, `learning`); `SlotStatus`; `FlowFlagType`.
- **Contracts in `strong_core.schemas.stories`:**
  - `StoryOutline`, `OutlineSection`, `OutlineSlot`, `ActionStep` and `ResultMetric`;
  - `CraftReply`, which replaces `CoachReply` for styled stories, with `message`,
    `slot_updates[]` (each with section, slot, text and quotes), `skips[]`, `section_done`,
    `skills` and `hints[]`;
  - `FlowCheck`, with `flags[]` (each with type, slots and question);
  - `SectionImprove` (edits or questions);
  - `OrganizeResult` (an outline with quotes).

  Run `dev.ps1 schemas` after these change.
- **Migration:** `stories.style` (enum, nullable) and `stories.outline_json` (JSONB, nullable).
  Classic stories have both null. `coach_sessions.section` (nullable) records the section in
  progress. The migration needs a working `downgrade()`. No backfill (D-11).
- **Model role:** stays `coach`. No new role; capabilities stay as configured.

### API (`apps/api/strong_api/coach`, `stories`)

- `engine.py`: a new `next_ask(outline, style)` returns the section and the empty slots, in the
  D-7 order. The renderer `render_legacy(outline)` implements SC-14. `ready(outline)` implements
  SC-3. `suggest_style(skill)` implements D-2.
- Session start takes `style`. A styled session runs `craft.turn`; classic stories keep today's
  turn until they are organized.
- New endpoints:
  - `PATCH /stories/{id}/outline`: inline slot edits (SC-10);
  - `POST /stories/{id}/sections/{section}/improve`: SC-11;
  - `POST /stories/{id}/flow-check` and `POST /stories/{id}/flow-flags/{key}/dismiss`: SC-9;
  - `POST /stories/{id}/organize` and `POST /stories/{id}/organize/accept`: SC-13;
  - `POST /stories/{id}/style`: SC-12;
  - `POST /stories/{id}/hints/{skill}/deepen|dismiss`: SC-8.

  Every write runs `render_legacy` and recomputes the status, story fit (ST-5) and versions as
  today.
- Skill hints use the role story-fit data (`role_story_fits`) for the gap order.

### Prompts (`prompts/coach/`)

- New: `craft_turn.v1.txt` and its input, with the section, the empty slots, the skipped slots,
  the style and the D-6 rules. Also `flow_check.v1.txt`, `improve_section.v1.txt`,
  `organize.v1.txt` and `rewrite_style.v1.txt`. Each gets a `small` variant where the tier needs
  one (PL-5).
- `review.v2.txt` works on sections.
- Fake fixtures for each new output type, plus recordings for the conformance suite (CO-1).

### Web (`apps/web`)

- **Start crafting:** a STAR or CARL picker with the suggestion.
- **Session screen:** the conversation is wide, and the outline panel shows sections with slot
  chips (filled, empty or skipped). The reply box grows with the text and has **Expand**,
  formatting and "skip" or "move on" quick replies. When the core slots are filled, the panel
  shows the skill hints.
- **Story page:** the outline with inline slot editors, **Improve with Strova** per section, flow
  flags, **Switch to STAR/CARL**, and the classic view with **Organize with Strova**.
- **Markdown:** a small toolbar over a textarea. It renders through a safe Markdown subset, with
  no raw HTML.

### Evals (`evals/`)

- The no-new-facts suite (SC-15) runs on crafting, improve, organize and rewrite fixtures.
- A depth suite checks that every context slot is asked once and a skipped slot is never asked
  again.
- A flow-check suite uses seeded incoherent stories to check that each flag type is found.

## Delivery plan

The plan is `docs/story-crafting/execution-plan.md`: nine tasks, SC00 to SC08, each one PR into
`main`, built unattended by one loop session (`docs/story-crafting/prompts/LOOP.md`). The order
is:

1. spec on `main`;
2. core;
3. the engine and craft turn;
4. the story APIs;
5. the session UI;
6. the story page UI;
7. the flow check and skill hints;
8. formatting and voice;
9. evals, end-to-end and the report.

## Open items

- The exact Strova copy for the section-opening questions; to review with the first prompts.
- Whether **Deepen** on a skill hint adds slots to this story or offers a new story when the skill
  doesn't fit. Default: add a short "Also shows" note with quotes to this story.
- The limits per slot and per story (R3 word limits). Default: keep today's per-part limits on the
  rendered legacy columns.
