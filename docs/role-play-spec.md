# Strong Hire Role-play Interviews and the Sales Family: Product & Technical Spec v1

Status: draft for review, 2026-11-02. Decisions D-1 to D-12 below.
This spec is wave 2 of `docs/role-families-spec.md` (D-12). It extends `docs/spec.md` (IV-2
interview types, IV-3 follow-up rules, IV-4 difficulty, IV-7 the state machine, the brief, the
rubric) the way RS-1 and RS-2 added the recruiter screen.

## Overview

Sales hiring turns on one round the product cannot simulate today: a mock sales call. The
candidate leads a discovery or pitch conversation, and an interviewer plays the buyer, holds back
what the buyer knows until good questions earn it, and raises objections. Voice is a better fit
for this than for any round Strong Hire runs now, and most generic interview-prep tools do not
offer it.

This spec adds one interview type, **Role-play** (`role_play`), and one role family, **Sales**
(`sales`). The same type later serves customer success (an escalation call) and other roles where
the loop has a scenario round; those come after this spec.

### Decisions

| ID | Decision |
| --- | --- |
| D-1 | Role-play is a new `InterviewType` (`role_play`), a sixth type next to the five. It is not a mode of an existing type: its turns, competencies and rubric differ. |
| D-2 | Strova steps into character. INTRO and AGENDA stay Strova as the interviewer, who sets the scene ("I'll play Dana, VP of Operations at a mid-size freight company; you're the account executive; your goal is a booked demo"). CORE is the call, with Strova as the buyer. CANDIDATE_QUESTIONS becomes a short step-out ("How do you think that went?"). WRAP_UP is Strova again. |
| D-3 | The call runs as **beats**, which reuse the controller's question machinery. A beat is a `BriefQuestion` whose text is the buyer's opening line for that stage and whose notes stay hidden from the candidate. The candidate leads; the buyer's replies are the beat's follow-ups, capped by the same probe limit. The controller still owns time, phase changes and the end of the session (IV-7). The model never decides when the call ends. |
| D-4 | A hidden **buyer brief** on the interviewer brief drives the buyer: who they are, their situation, the pains they reveal only to good discovery questions, budget, decision process, the objections to raise and when, and what earns the next step. The planner writes it from the job posting and the company profile. The candidate never sees it before the debrief. |
| D-5 | Four scenario kinds in v1: **cold call** (open and earn a meeting), **discovery call** (uncover pain and qualify), **demo and objections** (connect value to pain and handle pushback), and **negotiation and close** (pricing pushback and a committed next step). The candidate picks one at setup; the default comes from the level: new grad and mid get cold call or discovery, senior and staff get demo and objections. |
| D-6 | Four new competencies, scored only in role-play: `discovery`, `objection_handling`, `value_articulation`, `closing` (a concrete next step agreed). Role-play also scores the existing `communication`. |
| D-7 | Follow-up rules for role-play (IV-3 for a call): after each candidate turn the decide step chooses whether the buyer keeps the beat going or the beat ends. New `ProbeTrigger` values say why it continues: `needs_discovery` (the candidate pitched before asking), `objection_unresolved`, `no_value_link` (a feature with no tie to the buyer's pain), `no_next_step`. The same-gap rule still stops a beat that loops. |
| D-8 | Difficulty keeps its meaning (IV-4). Friendly: the buyer is open and offers hints. Realistic: the buyer reveals pain only when asked. Tough: the buyer is skeptical, raises every objection in the brief, and adds one curveball (for example "we just renewed with your competitor"). Tone (TN-1) still sets how Strova sounds, not how hard the buyer is. |
| D-9 | The buyer never invents facts about the candidate's real employer. The product being sold comes from the posting; if the posting names none, the planner describes a plausible product in the company's space and labels it in the scene setting. The buyer does not check product claims; the scorer judges how the candidate sells, not whether a feature exists. |
| D-10 | Add the `sales` role family: SDRs and BDRs, account executives, account managers, sales managers, and sales engineers whose loop centers on demos. Generic loop: recruiter screen, role-play, hiring manager. Rated in the gap analysis: the common six plus `role_fit` and `judgment` (resume evidence of quota attainment and deal judgment). |
| D-11 | Role-play is labeled **Beta** on the target role page until it has 5 human-scored gold transcripts, the same rule as RF-14. |
| D-12 | Coach mode works as for other types: hints and redo between buyer turns (IV-8). A hint never reveals the hidden buyer brief; it says what kind of move is missing ("ask about their current process"). |

## Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| RP-1 | `InterviewType.ROLE_PLAY` exists, with its own competencies (D-6) in `COMPETENCIES_BY_TYPE`. A migration widens every interview type and competency check constraint, with a working `downgrade()` that deletes role-play rows first, as 0021 did for recruiter screen. | P0 |
| RP-2 | `RoleFamily.SALES` exists, with a registry entry: label "Sales", title keywords (sales, account executive, sdr, bdr, business development, account manager, sales engineer), rated competencies (D-10), interviewer titles, and the generic loop (D-10). It has a family guidance prompt (D-7 of the role families spec). | P0 |
| RP-3 | `InterviewerBrief.role_play` holds the buyer brief (D-4): persona name and title, company summary, situation, hidden pains, budget, decision process, objections (each with when to raise it), curveball (Tough only) and success condition. It is required when the session type is role-play and absent otherwise. Stored briefs without it still load. | P0 |
| RP-4 | The planner writes the buyer brief and 2 to 4 beats for the chosen scenario kind (D-5) from the job posting, the company profile, the level and the difficulty. A 10-minute mini has one beat. | P0 |
| RP-5 | The live interviewer uses a role-play turn prompt: in CORE it speaks only as the buyer, follows the buyer brief, reveals hidden pains only when asked, and raises objections as the brief says. It never coaches or scores in character. The scene-setting and the step-out are spoken as Strova. | P0 |
| RP-6 | The decide step for role-play returns the triggers in D-7. The controller applies the probe limit and the same-gap rule to beats exactly as to questions. | P0 |
| RP-7 | The scorer has a role-play rubric. It scores D-6's competencies 1 to 4 with quotes from the candidate's turns, reads the buyer brief to judge discovery (which pains were uncovered) and closing (whether the success condition was met), and leaves the buyer's own lines out of the evidence. | P0 |
| RP-8 | Session setup offers Role-play with a scenario kind picker (D-5) and the level default. The live room shows "Role-play: you are the seller. Strova plays {persona name}, {title}". | P0 |
| RP-9 | The debrief for a role-play shows, per beat, what the buyer was hiding, what the candidate uncovered, and the objections and how each was handled. | P0 |
| RP-10 | The extractor (job posting prompt) classifies sales postings into `sales`, and maps titles to levels (SDR or BDR = new_grad, AE = mid, senior or enterprise AE = senior, sales director and above = staff_principal). | P0 |
| RP-11 | Eval fixtures: at least 4 sales postings; a role-play candidate behavior for the AI candidate (`prompts/candidate/`) and one sim scenario per scenario kind; a role-play fake fixture for each new contract. | P0 |
| RP-12 | Question bank: at least 15 general questions for `sales` (behavioral and hiring manager), and at least 8 role-play scenario cards (one buyer situation each) on the Questions page. | P1 |
| RP-13 | Gold transcripts: 5 human-scored role-play transcripts, one or more per scenario kind. Until they exist, role-play and the sales family are labeled Beta (D-11). | P1 |

## Build plan

The same order as wave 1. Each step is one PR with green CI.

| Step | PR | IDs |
| --- | --- | --- |
| 1 | **Core**: `role_play` type, new competencies and probe triggers, `sales` family and registry entry, `RolePlayBrief` on the brief, migration, schemas, labels. | RP-1, RP-2, RP-3 |
| 2 | **Planner, interviewer and scorer**: buyer brief and beats, role-play turn and decide prompts, controller rules, role-play rubric, sales family guidance, extractor v3. | RP-4 to RP-7, RP-10 |
| 3 | **UI**: setup scenario picker, live-room label, debrief per beat, Beta label. | RP-8, RP-9, D-11 |
| 4 | **Evals**: sales postings, AI-candidate role-play behavior, sim suite. | RP-11 |
| 5 | **Content**: sales questions and scenario cards. Gold transcripts need people. | RP-12, RP-13 |

## Risks

| Risk | Mitigation |
| --- | --- |
| A small model breaks character or coaches the candidate mid-call | Role-play prompts keep the buyer to one short reply; the guard already checks every interviewer turn (IV-12); hints only in Coach mode and only as Strova |
| The buyer gives away the hidden pains at once | Hidden pains are passed with a rule ("say this only when asked about X"), and the decide step, not the buyer, judges discovery |
| The scorer credits the buyer's words to the candidate | The rubric input marks speaker turns, and RP-7 scores only candidate turns |
| Product facts are invented for a real company | D-9: the product comes from the posting or is labeled as illustrative in the scene |
| Latency: a buyer reply needs the buyer brief in context | The buyer brief is short (about 150 words) and goes in the system prompt once per session |
