# Strong Hire Role Families: Product & Technical Spec v1

Status: draft for review, 2026-10-31. Decisions D-1 to D-12 below.
This spec extends `docs/spec.md` (Scope "Roles" row, IN-2, IV-2, IV-6, the interviewer brief, the
rubric, QB-1 to QB-5, the profile structure) and the v2.1 plan screens (TG-3, ux-spec 4.1).

## Overview

Goal: grow the addressable market from five tech role families to every white-collar role whose
interviews are mostly conversation, without new infrastructure. Voice sessions, the five interview
types, the 1 to 4 rubric, level bars, the hire signal and Strova coaching already work for any
role. Only a few places assume tech roles: the `RoleFamily` enum, the competencies the gap analysis
rates, the title keywords, the extractor's classification rules, the generic-mode wording, the
default interviewer titles, the recruiter screen prompts, the question bank and the company
loops.

This spec covers **wave 1**: two splits of existing families and four new families. Sales
role-play is **wave 2** and gets its own spec, because it needs a new interview type.

### Decisions

| ID | Decision |
| --- | --- |
| D-1 | Split `swe` into `swe` (application, backend, frontend, mobile, platform software) and a new `infra_security` (SRE, DevOps, cloud, network, security, IT systems). |
| D-2 | Split `data_ml` into `data_ml` (data science, machine learning, data engineering) and a new `data_analytics` (data, BI, product and business analysts, analytics engineers). |
| D-3 | Add four families: `eng_management`, `finance`, `consulting_strategy`, `project_program`. |
| D-4 | Existing enum values are kept. A split narrows what the old value means; it renames nothing, so stored rows stay valid. |
| D-5 | No new `Competency` values in wave 1. The interview type still decides the scored competencies (spec "Competencies by interview type"). The family decides what each type is *about*: the topics of a technical Q&A, the kind of case, the interviewer's title, and the competencies the gap analysis rates. |
| D-6 | One registry in `strong_core` holds every per-family fact that is data: label, title keywords, rated competencies, interviewer titles by type, generic loop. Code reads the registry; no other module keeps a per-family dict. A test fails when a `RoleFamily` value has no registry entry. |
| D-7 | Everything per family that is prose for a model lives in a planner prompt, `prompts/planner/family_<value>.v1.txt`, never in Python. A test fails when a family has no prompt. |
| D-8 | Live coding, whiteboards, written take-homes and portfolio uploads stay out of scope. A family qualifies only if a voice session can simulate most of its loop. |
| D-9 | Generic mode gets a per-family default loop, so a candidate for a company with no profile still gets the right suggested interviews (TG-3). |
| D-10 | Existing job targets are reclassified once by a rule-based script (title keywords only, no model calls). After that, users change the family on the confirm step as today. |
| D-11 | No feature flag. Today a finance or consulting posting lands in `other`, with no family guidance at all. Each new family is a strict improvement from the day it ships, even before its question content lands. |
| D-12 | Wave 2 (separate spec): `sales` with a new role-play interview type, then `customer_success`, `marketing`, `people_hr`. |

## Families

The six existing families keep their meaning except where D-1 and D-2 narrow it. US employment
figures are rough orders of magnitude for sizing only; check them before using them in a pitch.

| Value | Label | Covers | Not this family | Approx. US size |
| --- | --- | --- | --- | --- |
| `swe` | Software engineering | Application, backend, frontend, mobile, full-stack, platform and ML-infrastructure software engineers | SRE, DevOps, security (→ `infra_security`); engineering managers (→ `eng_management`) | ~1.7M |
| `infra_security` | Infrastructure and security | SRE, DevOps, cloud, platform operations, network engineers, security engineers and analysts, IT systems administrators | Software engineers who mainly write product code | ~1.5M |
| `data_ml` | Data science and ML | Data scientists (modeling), ML engineers and researchers, data engineers | Analysts whose work is SQL, dashboards and reporting (→ `data_analytics`) | ~0.4M |
| `data_analytics` | Data analytics | Data, BI, product, marketing and business analysts; analytics engineers | Roles that build models or pipelines as the main output (→ `data_ml`) | ~1M |
| `pm` | Product management | Unchanged | | |
| `design` | Design | Unchanged | | |
| `tpm` | Technical program management | Unchanged. A program role where the posting asks for engineering or systems depth | Non-technical program and project roles (→ `project_program`) | |
| `eng_management` | Engineering management | Engineering managers, senior managers, directors and heads of engineering | Tech leads with no direct reports (→ `swe`) | ~0.5M |
| `finance` | Finance | FP&A, financial analysts, accountants, controllers, treasury, corporate finance, investment banking and markets analysts | Finance software engineers (→ `swe`); quant researchers (→ `data_ml`) | ~2M |
| `consulting_strategy` | Consulting and strategy | Management consultants, strategy and operations, BizOps, corporate development, chiefs of staff | IT or implementation consultants with a technical focus (→ the technical family) | ~1M |
| `project_program` | Project and program management | Project managers, non-technical program managers, PMO, delivery managers, scrum masters | Program roles that ask for engineering depth (→ `tpm`) | ~1M |
| `other` | Other | Anything else | | |

### Per-family registry (D-6)

`G` = the generic default loop (D-9), in order. Interviewer titles apply when the company profile
names no interviewer for that round (ux-spec 4.1). Recruiter screen is always "Recruiter" and
Custom is always "Interviewer", in every family.

| Family | Rated competencies in the gap analysis (each also rates the common six*) | Title keywords | Behavioral | Hiring manager | Technical Q&A | Case | G |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `swe` | technical_depth, trade_offs | engineer, developer, software, full stack, frontend, backend, mobile | Engineering Manager | Hiring Manager | Senior Engineer | Product Lead | BEH, HM, TQA |
| `infra_security` | technical_depth, trade_offs | sre, site reliability, devops, infrastructure, cloud, platform, network, security, systems administrator, it | Engineering Manager | Hiring Manager | Senior Infrastructure Engineer | Engineering Manager | BEH, HM, TQA |
| `data_ml` | technical_depth, trade_offs | data scientist, machine learning, ml, data engineer, ai, research scientist | Data Science Manager | Hiring Manager | Senior Data Scientist | Product Lead | BEH, HM, TQA |
| `data_analytics` | technical_depth, problem_framing | analyst, analytics, business intelligence, bi, insights, reporting | Analytics Manager | Hiring Manager | Senior Data Analyst | Analytics Manager | BEH, TQA, CASE |
| `pm` | user_and_business_sense, prioritization | unchanged | Product Lead | Hiring Manager | Engineering Lead | Product Lead | BEH, HM, CASE |
| `design` | user_and_business_sense, problem_framing | unchanged | Design Manager | Hiring Manager | Design Lead | Product Lead | BEH, HM, CASE |
| `tpm` | technical_depth, prioritization | technical program manager, tpm | Engineering Manager | Hiring Manager | Senior Engineer | Program Lead | BEH, HM, TQA |
| `eng_management` | judgment, prioritization | engineering manager, manager of engineering, director of engineering, head of engineering, vp engineering | Director of Engineering | VP of Engineering | Principal Engineer | Director of Engineering | BEH, HM, TQA |
| `finance` | technical_depth, problem_framing | finance, financial, fp&a, accountant, accounting, controller, treasury, investment banking, analyst (with a finance word) | Finance Manager | Hiring Manager | Senior Financial Analyst | Finance Director | BEH, TQA, CASE |
| `consulting_strategy` | problem_framing, user_and_business_sense | consultant, consulting, strategy, bizops, business operations, corporate development, chief of staff | Senior Manager | Hiring Manager | Senior Consultant | Engagement Manager | CASE, BEH, HM |
| `project_program` | prioritization, judgment | project manager, program manager, pmo, delivery manager, scrum master | Program Director | Hiring Manager | Senior Program Manager | Program Director | BEH, HM, CASE |
| `other` | (common six only) | | Hiring Manager | Hiring Manager | Subject Expert | Hiring Manager | BEH, HM, TQA |

\* The common six: ownership, impact, collaboration, communication, depth_of_experience,
scope_at_level (`_COMMON` today).

For `pm` and `design`, the generic loop changes from the current BEH, HM, TQA to BEH, HM, CASE, and
the `design` technical interviewer changes from "Senior Engineer" to "Design Lead". These fix
wrong defaults that apply today.

### Per-family guidance prompts (D-7)

Each `prompts/planner/family_<value>.v1.txt` states, in at most about 200 words:

1. **Technical Q&A topics**: what a verbal technical round covers for this family, and what it
   never covers (no live coding, no written work).
2. **Case kinds**: what a case is for this family. The company profile's `case_style` still
   weights the case (product sense, estimation, system thinking).
3. **Level notes**: how the family's titles map to the four normalized levels, and what changes in
   scope.
4. **Words to use**: the family's own terms, so the interviewer sounds like someone from the
   field.

Wave 1 content:

| Family | Technical Q&A | Case | Level notes |
| --- | --- | --- | --- |
| `infra_security` | Incidents and postmortems, reliability and SLOs, networking, cloud architecture, observability, capacity, threat modeling, access control, vulnerability handling | An outage or capacity scenario to triage out loud; a threat-model walkthrough | Operations scope grows from one service, to a platform, to an org-wide reliability or security program |
| `data_analytics` | SQL concepts explained verbally (joins, windows, aggregation pitfalls), metric definitions, A/B test design and reading, statistics basics, dashboard and data-quality judgment | Diagnose a metric drop; define success metrics for a launch; size an opportunity from data | From answering questions, to owning a domain's metrics, to setting how the org measures |
| `eng_management` | Architecture and delivery trade-offs at design-review level, operational excellence, technical debt strategy, build vs buy. Never hands-on coding | Team or org scenarios: an underperformer, roadmap vs technical debt, a headcount plan, a missed launch | mid = first-line manager (M1), senior = senior manager or manager of managers, staff_principal = director and above |
| `finance` | The three statements and how they link, valuation (DCF, multiples), variance analysis, budgeting and forecasting, working capital, unit economics; for banking and markets roles, deal and markets basics | An investment or pricing decision, a profitability drop, a budget trade-off, with numbers worked out loud | Analyst = new_grad or mid, Associate or Senior Analyst = mid, Manager or VP = senior, Director and above = staff_principal |
| `consulting_strategy` | Rare. For BizOps and strategy roles, metrics and simple quantitative reasoning | Interviewer-led and candidate-led business cases: profitability, market entry, market sizing, M&A, operations; ends with a synthesis | Business Analyst = new_grad, Associate or Consultant = mid, Engagement Manager = senior, Associate Partner and above = staff_principal |
| `project_program` | Delivery methods (agile, waterfall, hybrid), planning, critical path, risk and issue logs, scope, budget and change control, stakeholder mapping, reporting | A slipping project, scope creep, a conflict between two sponsors, a recovery plan | From one project, to a program of projects, to a portfolio or PMO |

The existing five families get a prompt too, written from what the brief and the profiles already
assume, so every family is handled the same way.

## Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| RF-1 | `RoleFamily` has the six wave-1 values next to the six existing ones (D-1 to D-4). A migration widens the waitlist `role_family` CHECK constraint (the only database column with that enum; job targets keep it in `parsed_json`), with a working `downgrade()` that first maps new values to `other`. `schemas/` is regenerated. | P0 |
| RF-2 | The core registry (D-6) has one entry per `RoleFamily` value: label, title keywords, rated competencies, interviewer title per interview type, and the generic loop. Gap analysis, confidence, plan suggestions and "acting as" read it. No other module keeps a per-family mapping. | P0 |
| RF-3 | The extractor (job posting prompt v2) classifies into all twelve families, using the "Covers" and "Not this family" rules above, and maps family-specific level titles (finance, consulting, management) to the four normalized levels. | P0 |
| RF-4 | Extractor accuracy: the inputs eval set has at least 4 real-looking postings per new family and 2 per narrowed boundary (SWE vs infra, data science vs analytics, TPM vs program, tech lead vs EM). Role family accuracy is at least 90 percent on the hosted profile. | P0 |
| RF-5 | The interviewer brief gets the family and the family's guidance prompt (D-7). Technical Q&A questions fit the family's topics, and case prompts fit the family's case kinds. | P0 |
| RF-6 | The scorer gets the family's level notes with the seniority bar (IV-6). The rubric and its scale do not change. | P0 |
| RF-7 | Generic mode wording no longer says "tech industry": the bar is "a typical bar for this role family at a large North American employer". | P0 |
| RF-8 | The recruiter screen prompts (v2) say the recruiter is not a specialist in the role, instead of "not an engineer". | P0 |
| RF-9 | In generic mode, suggested interviews follow the family's generic loop (D-9). Without a named interviewer, "Strova is acting as" uses the family's title for that type. | P0 |
| RF-10 | The web and admin labels, the Questions page filter, the job confirm step and the waitlist form list all twelve families with the labels above. | P0 |
| RF-11 | A one-off rule-based script reclassifies stored job targets and waitlist entries whose title matches a new family's keywords (D-10). It makes no model calls, prints every change, and has a dry-run default. | P0 |
| RF-12 | Question bank: at least 15 general questions per new family in `questions/general.json`, with at least 3 for each of behavioral, hiring manager, technical Q&A and case (consulting may have 0 technical Q&A and 6 or more case). Each has hints that follow QB-5. | P1 |
| RF-13 | Company loops: `loop_structure` and `bar_by_level` entries for new families at the profiled companies that hire them. `mckinsey` moves its `other` loop to `consulting_strategy`. First: `eng_management` at every tech profile; `finance` at goldman-sachs and jpmorgan; `consulting_strategy` at mckinsey; `infra_security` at cloudflare and datadog; `data_analytics` at meta, google, amazon and airbnb. | P1 |
| RF-14 | Scorer calibration: at least 5 gold transcripts per new family in `evals/transcripts`, and the hire signal agreement target (85 percent within one band) holds on them. A family without its 5 is labeled "Beta" on the target role page until it has them. | P1 |
| RF-15 | Sim scenarios: one text scenario per new family in `evals/scenarios`, run in the nightly sim. | P1 |

Every new family also passes the existing tests for every-family coverage (fake fixtures, contract
validation, the model-name scan, the gateway rule).

## Build plan

Each step is one PR with green CI. Steps 3 to 5 can run in parallel after step 2 merges.

| Step | PR | Owner (CLAUDE.md folders) | IDs |
| --- | --- | --- | --- |
| 1 | **Core**: enum values, migration, registry module, schema regen. Small and separate, merges first. | `packages/core`, `schemas/` | RF-1, RF-2 (registry only) |
| 2 | **Prompts and wiring**: extractor job posting v2, family guidance prompts, brief and scorer inputs, generic wording, recruiter screen v2; gap analysis, confidence and plan read the registry; fake fixtures re-recorded. | `prompts/`, `apps/worker`, `apps/api`, core fixtures | RF-2, RF-3, RF-5 to RF-9 |
| 3 | **UI**: labels, filters, confirm step, waitlist form. | `apps/web`, `apps/admin` | RF-10 |
| 4 | **Evals and backfill**: extractor eval postings, reclassify script, sim scenarios. | `evals/`, `scripts/` (PowerShell) | RF-4, RF-11, RF-15 |
| 5 | **Content**: question bank and profile loops, one PR per family. Gold transcripts follow. | `questions/`, `profiles/`, `evals/transcripts` | RF-12 to RF-14 |

Notes for step 2:
- Bumping a prompt version changes the message hash, so exact fake recordings for the extractor,
  planner and scorer must be re-recorded. `<OutputType>.json` fixtures are not affected.
- Wave 1 adds no new `Competency` values, so `COMPETENCIES_BY_TYPE`, the rubric prompts and the
  debrief do not change.

## Risks

| Risk | Mitigation |
| --- | --- |
| Small models confuse the boundary families (SWE vs infra, TPM vs program) | RF-4 boundary postings; the confirm step lets the user fix the family; the keyword confidence (IN-2) flags a mismatch |
| Finance and consulting technical answers need domain accuracy the scorer may lack | RF-14 gold transcripts per family before the "Beta" label comes off; Tough mode stays honest by scoring on evidence in the transcript |
| Content load: 90 or more new questions and many profile loops | RF-12 and RF-13 are P1 and ship per family; generic mode works without them |
| Banking superdays and consulting cases often include written exhibits | Out of scope (D-8). Exhibits are described aloud; the family prompt says so |
