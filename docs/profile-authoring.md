# Authoring a company profile

This guide explains each field of a company profile file and shows one full example.
It covers requirement AD-1. The spec section "Company profiles" in `docs/spec.md` gives the
background.

## The file and the schema

- One JSON file per company, saved in `profiles/<company-slug>.json`.
- The schema is `schemas/company_profile.schema.json`. It is generated from the Pydantic
  model `strong_core.schemas.CompanyProfile`. Do not edit the schema by hand.
- Unknown fields are rejected. A spelling mistake in a field name fails validation.
- Write patterns and expectations only. Do not include leaked or NDA-protected questions, copied
  paid content, or claims about named interviewers.

## Workflow

```powershell
uv run strongctl profiles validate profiles/acme.json   # checks the file, no database
uv run strongctl profiles import profiles/acme.json     # stores the next version as Draft
uv run strongctl profiles publish acme 2                # makes version 2 the active profile
uv run strongctl profiles list                          # published and latest version per company
uv run strongctl profiles show acme --version 1         # read any version, also old ones
```

- `import` validates the file again, stores it as the next version number for that company,
  and prints a field-by-field diff against the published version. It does not publish.
- The database assigns version numbers. `meta.version` in the file is for your own tracking.
- `import` refuses a file whose content equals the latest stored version. Use `--force` to
  store it anyway.
- `import` fails if the company is not in the companies table. The 20 launch companies come
  from the seed (`./scripts/dev.ps1 seed`). For a test company, pass `--create-company`.
  It adds the company as inactive, so job matching (IN-5) does not use it.
- `publish` asks for confirmation (`--yes` skips it) and records the reviewer
  (`--reviewer`, default: your user name). The version that was published before becomes
  Archived. Archived versions stay readable, so old sessions keep their scores explainable.
- Sessions store the version they used in `sessions.profile_version`. Generic mode stores NULL.
- The commands use `DATABASE_URL`. The default is the local Docker Postgres on port 55432.

## Fields

| Field | Required | What to write |
| --- | --- | --- |
| `company_name` | Yes | Display name, for example "Example Corp". |
| `company_slug` | Yes | Lowercase letters, digits and single hyphens. Must match the companies table, for example `google`. |
| `meta.version` | Yes | Integer, 1 or more. Your own counter; the database assigns the stored number. |
| `meta.status` | No | Leave `draft`. Import always stores a Draft. |
| `meta.reviewed_by` | No | Your name if you reviewed the file. `publish` sets the reviewer. |
| `meta.researched_at` | No | Date of the research, `YYYY-MM-DD`. |
| `meta.published_at` | No | Leave `null`. `publish` sets it. |
| `values_framework.name` | Yes | Name of the company's principles, for example "Leadership Principles". |
| `values_framework.principles[]` | Yes, 1 or more | Each has `name`, `description`, `evidence_signals` (1 or more), and `weight`. `evidence_signals` says what evidence of the value sounds like in an answer. Names must be unique. Briefs and scorecards use the name as the value's id, so keep it the same across versions. |
| `values_framework.principles[].weight` | No | Positive number, default 1.0. The weight of this value inside the values share. |
| `loop_structure[]` | Yes, 1 or more | One entry per role family (`swe`, `data_ml`, `pm`, `design`, `tpm`, `other`). `levels` lists company level names. `rounds[]` (1 or more) has `name`, `interview_type`, `duration_min` (5 to 240), `interviewer_role`, `notes`. |
| `loop_structure[].rounds[].interview_type` | No | One of `behavioral`, `hiring_manager`, `technical_qa`, `case`. Use `null` for rounds v1 does not simulate, such as live coding. |
| `question_patterns[]` | Yes, 1 or more | `interview_type`, `theme`, `pattern`, optional `competencies`, and optional `values`. Write a pattern, never a real question. |
| `question_patterns[].values` | No | Principle names from `values_framework` that this pattern probes. An unknown name fails validation. |
| `bar_by_level[]` | Yes, 1 or more | `level_name` (company label, for example "E5"), `normalized_level` (`new_grad`, `mid`, `senior`, `staff_principal`), optional `role_family`, and `scope_expectation`. |
| `persona` | Yes | `tone`, `pace`, `pushback_style`, `closing_style`. The interviewer uses these (IV-5). |
| `scoring_weights` | Yes, 1 or more | Competency name to a positive number. Competencies you leave out weigh 1.0. Use values above 1.0 for what the company stresses. |
| `values_share` | No | Number from 0 to 0.5, default 0.25. The share of the hire signal that comes from company value scores. Competency scores give the rest. |
| `case_style` | Yes | `product_sense`, `estimation`, `system_thinking`, each from 0 to 1, plus optional `notes`. |
| `sources[]` | Yes, 1 or more | `url`, optional `title`, `retrieved_at` (`YYYY-MM-DD`), and `fields`: the profile fields this source supports. Public sources only. |
| `field_confidence` | Yes | `low`, `medium` or `high` for each of these 7 fields: `values_framework`, `loop_structure`, `question_patterns`, `bar_by_level`, `persona`, `scoring_weights`, `case_style`. All 7 are required. |
| `low_confidence_notes[]` | No | Short notes for the reviewer about weak claims. Start each with the field name. |

Competency names for `scoring_weights` and `question_patterns[].competencies`:

- Behavioral: `ownership`, `impact`, `collaboration`, `conflict_handling`,
  `learning_from_failure`, `communication`.
- Hiring manager: `role_fit`, `depth_of_experience`, `judgment`, `motivation`, `team_fit`,
  `scope_at_level`.
- Technical Q&A: `technical_depth`, `accuracy`, `reasoning`, `trade_offs`,
  `clarity_of_explanation`.
- Case: `problem_framing`, `structure`, `user_and_business_sense`, `estimation_logic`,
  `prioritization`, `recommendation`.

## Error messages

Validation names the bad field with a dotted path. Examples:

```text
Invalid profile file: profiles/acme.json
  - values_framework.principles[0].evidence_signals: List should have at least 1 item after validation, not 0
  - persona.tone: Field required
  - scoring_weights.speed (key): Input should be 'ownership', 'impact', ...
  - case_style.estimation: Input should be less than or equal to 1
  - (profile): field_confidence is missing: case_style
  - (profile): question_patterns use unknown values: Move fast
```

## Generic mode

A company without a published profile runs in generic mode: a default tech-industry persona
and equal competency weights (spec, "Companies outside the 20"). Code gets it from
`strong_api.profiles.resolve_profile(db, company_id)`. The result has `version = None` and
`generic = True`.

## Full example (fictional company)

Example Corp is not a real company. The same file is `profiles/examples/example-corp.json`.
A test checks that this block and the file are equal and valid.

```json
{
  "company_name": "Example Corp",
  "company_slug": "example-corp",
  "meta": {
    "version": 1,
    "status": "draft",
    "reviewed_by": null,
    "researched_at": "2026-10-03",
    "published_at": null
  },
  "values_framework": {
    "name": "Example Values",
    "principles": [
      {
        "name": "Customer first",
        "description": "Start from the customer problem and measure the result for the customer.",
        "evidence_signals": [
          "Names a specific customer or user group and their pain",
          "Shows how the outcome was measured for the customer"
        ],
        "weight": 1.0
      },
      {
        "name": "Own the outcome",
        "description": "Take responsibility end to end, including after launch.",
        "evidence_signals": [
          "Uses 'I' for own decisions and 'we' for team work",
          "Follows through after launch and fixes what broke"
        ],
        "weight": 1.5
      }
    ]
  },
  "loop_structure": [
    {
      "role_family": "swe",
      "levels": ["E3", "E4", "E5", "E6"],
      "rounds": [
        {
          "name": "Recruiter screen",
          "interview_type": null,
          "duration_min": 30,
          "interviewer_role": "Recruiter",
          "notes": "Background, motivation and logistics. Not simulated in v1."
        },
        {
          "name": "Coding",
          "interview_type": null,
          "duration_min": 60,
          "interviewer_role": "Software engineer",
          "notes": "Live coding. Not simulated in v1."
        },
        {
          "name": "Technical deep dive",
          "interview_type": "technical_qa",
          "duration_min": 45,
          "interviewer_role": "Senior engineer",
          "notes": "Verbal questions about a past system the candidate built."
        },
        {
          "name": "Values interview",
          "interview_type": "behavioral",
          "duration_min": 45,
          "interviewer_role": "Senior engineer from another team",
          "notes": null
        },
        {
          "name": "Hiring manager",
          "interview_type": "hiring_manager",
          "duration_min": 45,
          "interviewer_role": "Engineering manager",
          "notes": "Scope, motivation and team fit."
        }
      ]
    },
    {
      "role_family": "pm",
      "levels": ["PM2", "Senior PM"],
      "rounds": [
        {
          "name": "Product sense case",
          "interview_type": "case",
          "duration_min": 45,
          "interviewer_role": "Senior product manager",
          "notes": null
        },
        {
          "name": "Values interview",
          "interview_type": "behavioral",
          "duration_min": 45,
          "interviewer_role": "Product leader",
          "notes": null
        }
      ]
    }
  ],
  "question_patterns": [
    {
      "interview_type": "behavioral",
      "theme": "Ownership under ambiguity",
      "pattern": "A time the candidate drove a result without clear direction or a clear owner",
      "competencies": ["ownership", "impact"],
      "values": ["Own the outcome"]
    },
    {
      "interview_type": "behavioral",
      "theme": "Disagreement with a peer",
      "pattern": "A time the candidate disagreed with a peer or manager and how it ended",
      "competencies": ["conflict_handling", "collaboration"],
      "values": []
    },
    {
      "interview_type": "hiring_manager",
      "theme": "Largest project",
      "pattern": "Walk through the largest project on the resume: the goal, own role, and result",
      "competencies": ["depth_of_experience", "scope_at_level"],
      "values": ["Own the outcome"]
    },
    {
      "interview_type": "technical_qa",
      "theme": "Design trade-offs",
      "pattern": "Explain a design choice in a past system and the option that was rejected",
      "competencies": ["trade_offs", "technical_depth"],
      "values": []
    },
    {
      "interview_type": "case",
      "theme": "Improve an existing product",
      "pattern": "Pick a user group of a product and propose one change, with a success metric",
      "competencies": ["problem_framing", "user_and_business_sense", "prioritization"],
      "values": ["Customer first"]
    }
  ],
  "bar_by_level": [
    {
      "level_name": "E3",
      "normalized_level": "new_grad",
      "role_family": "swe",
      "scope_expectation": "Delivers well-defined tasks with guidance from a senior engineer."
    },
    {
      "level_name": "E4",
      "normalized_level": "mid",
      "role_family": "swe",
      "scope_expectation": "Owns features within one team from design to launch."
    },
    {
      "level_name": "E5",
      "normalized_level": "senior",
      "role_family": "swe",
      "scope_expectation": "Owns systems and influences the plans of adjacent teams."
    },
    {
      "level_name": "E6",
      "normalized_level": "staff_principal",
      "role_family": "swe",
      "scope_expectation": "Sets technical direction for a group of teams."
    },
    {
      "level_name": "Senior PM",
      "normalized_level": "senior",
      "role_family": "pm",
      "scope_expectation": "Owns a product area and its metrics."
    }
  ],
  "persona": {
    "tone": "Friendly and curious",
    "pace": "Moderate, with short pauses for the candidate to think",
    "pushback_style": "Asks 'what would you do differently?' and for numbers",
    "closing_style": "Leaves 5 minutes for the candidate's questions"
  },
  "scoring_weights": {
    "ownership": 1.5,
    "impact": 1.2,
    "collaboration": 1.0,
    "conflict_handling": 1.0,
    "trade_offs": 1.2,
    "user_and_business_sense": 1.3
  },
  "values_share": 0.25,
  "case_style": {
    "product_sense": 0.6,
    "estimation": 0.2,
    "system_thinking": 0.2,
    "notes": "Cases start from a user problem. Estimation is a small part."
  },
  "sources": [
    {
      "url": "https://careers.example.com/values",
      "title": "Example Corp values",
      "retrieved_at": "2026-10-03",
      "fields": ["values_framework", "persona"]
    },
    {
      "url": "https://careers.example.com/how-we-hire",
      "title": "How we hire at Example Corp",
      "retrieved_at": "2026-10-03",
      "fields": ["loop_structure", "question_patterns", "case_style"]
    },
    {
      "url": "https://engineering.example.com/career-ladder",
      "title": "Example Corp engineering career ladder",
      "retrieved_at": "2026-10-02",
      "fields": ["bar_by_level", "scoring_weights"]
    }
  ],
  "field_confidence": {
    "values_framework": "high",
    "loop_structure": "medium",
    "question_patterns": "medium",
    "bar_by_level": "low",
    "persona": "medium",
    "scoring_weights": "low",
    "case_style": "low"
  },
  "low_confidence_notes": [
    "bar_by_level: level names come from one public source only.",
    "scoring_weights: estimated from the values page; no public source gives weights."
  ]
}
```
