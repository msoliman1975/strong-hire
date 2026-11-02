# Strong Hire Customer Success and the Escalation Call: Product & Technical Spec v1

Status: draft for review, 2026-11-02. Decisions D-1 to D-10 below.
This spec is wave 3 of `docs/role-families-spec.md`. It reuses the role-play interview type from
`docs/role-play-spec.md` (RP-1 to RP-13) and adds one call type and one role family.

## Overview

Customer success managers are hired on one round that looks like the sales role-play with the
roles turned around: a customer is unhappy, a renewal is at risk, and the candidate must calm the
call, find what went wrong, and agree a recovery plan. The role-play engine already runs a hidden
brief, beats, objections and a success condition. An **escalation call** is a fifth call type on
that engine, and **Customer success** (`customer_success`) is the family that uses it by default.

### Decisions

| ID | Decision |
| --- | --- |
| D-1 | Add `RolePlayScenario.ESCALATION_CALL` (`escalation_call`): an existing customer is upset (an outage, a failed rollout, a missed promise, a surprise bill) and the renewal is at risk. The candidate leads the call. No new interview type. |
| D-2 | Add the `customer_success` role family: customer success managers, technical account managers, implementation and onboarding managers, renewals managers, customer experience leads. Generic loop: recruiter screen, role-play, hiring manager. Rated in the gap analysis: the common six plus `role_fit` and `judgment` (resume evidence of retention, renewals and handling escalations). |
| D-3 | No new competencies. An escalation call scores the five role-play competencies, read for this call by the rubric: `discovery` = finding the root cause and what the customer needs; `objection_handling` = handling frustration and pushback without blame or empty promises; `value_articulation` = reconnecting the product to the customer's goals; `closing` = an agreed recovery plan with owners and dates; `communication`. This keeps the stored scores, progress charts and migrations unchanged. |
| D-4 | The buyer brief (RP-3) holds the customer. Its fields keep their names and change meaning for this call: `hidden_pains` are the facts behind the complaint the customer gives only to good questions; `budget` is the contract value and renewal date; `decision_process` is who decides on the renewal; `objections` are the escalation's flash points ("I want a refund", "I'm taking this to your CEO"); `success_condition` is the recovery step the customer agrees to. No contract field changes. |
| D-5 | The role-play persona title depends on the family: "Buyer" for sales, "Customer" for customer success, "Buyer" for every other family. The plan page reads "Strova is acting as a Customer". |
| D-6 | Every role-play session may pick any of the five call types. The setup default comes from the job's family first: customer success defaults to the escalation call at every level. Other families keep the level default (RP-4). |
| D-7 | The live room line follows the call type: "Role-play: you are the customer success manager. Strova plays {name}, {title}" for an escalation call, "you are the seller" otherwise. |
| D-8 | Difficulty keeps its meaning (IV-4, RP D-8). Friendly: the customer is annoyed but fair. Realistic: angry at first, calms when heard. Tough: angry, threatens to cancel, and adds one curveball (for example "your competitor already sent us a proposal"). |
| D-9 | The customer never invents facts about the candidate's real employer, as in RP D-9: the product and the incident come from the posting or are labeled illustrative. |
| D-10 | Customer success is labeled **Beta** until it has 5 human-scored gold transcripts (RF-14). |

## Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| CS-1 | `RolePlayScenario.ESCALATION_CALL` exists. Stored sessions with the other four call types still load. | P0 |
| CS-2 | `RoleFamily.CUSTOMER_SUCCESS` exists, with a registry entry: label "Customer success", title keywords (customer success, csm, client success, customer experience, technical account manager, implementation manager, onboarding manager, renewals), rated competencies (D-2), interviewer titles, the role-play persona title (D-5) and the generic loop (D-2). It has a family guidance prompt. A migration widens the waitlist role family check, with a working `downgrade()` that maps the new value to `other`. | P0 |
| CS-3 | The planner writes the customer brief and 2 to 4 beats for an escalation call (D-4), from the posting, the profile, the level and the difficulty. A mini has one beat. | P0 |
| CS-4 | The role-play turn and decide prompts handle the escalation call: the customer opens upset, calms only when heard, gives the facts behind the complaint only to good questions, and raises the flash points as the brief says (D-8). | P0 |
| CS-5 | The role-play rubric reads an escalation call as D-3 says. The scorer still quotes only candidate turns. | P0 |
| CS-6 | The extractor classifies customer success postings into `customer_success` and maps titles to levels (associate CSM = new_grad, CSM = mid, senior or enterprise CSM = senior, director of customer success and above = staff_principal). | P0 |
| CS-7 | Session setup and the target role page list the escalation call, default to it for customer success (D-6), and the live room line follows D-7. Customer success shows Beta (D-10). The site waitlist and guides name the family. | P0 |
| CS-8 | Eval fixtures: at least 4 customer success postings with gold extractions, a sim scenario for the escalation call, and the AI candidate plays the customer success manager in it. | P0 |
| CS-9 | Question bank: at least 15 general questions for `customer_success` (behavioral and hiring manager) and at least 4 escalation call scenario cards. | P1 |
| CS-10 | Gold transcripts: 5 human-scored escalation calls. Until they exist, customer success is Beta. | P1 |

## Build plan

| Step | PR | IDs |
| --- | --- | --- |
| 1 | **Core**: this spec, the call type, the family and registry entry, the persona title, migration, schemas, labels. | CS-1, CS-2 |
| 2 | **Engine and evals**: planner, turn, decide and rubric prompts for the escalation call, family guidance, extractor v4, postings, sim scenario. | CS-3 to CS-6, CS-8 |
| 3 | **UI and content**: setup default by family, live-room line, Beta, site, questions and scenario cards. | CS-7, CS-9 |

## Risks

| Risk | Mitigation |
| --- | --- |
| Reusing sales field names confuses the planner | The planner prompt restates D-4 for the escalation call; the contract descriptions mention both readings |
| The customer stays angry whatever the candidate does | The turn prompt says the customer calms when they feel heard and gets a concrete plan; the decide step ends a beat once its goal is met |
| Sales competency labels read oddly in a CS debrief | The rubric explains each competency for this call (D-3); renaming labels per call type can follow if users find them confusing |
