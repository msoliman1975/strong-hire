/**
 * Mock payloads. Each one is typed with a shared contract from packages/core, and
 * fixtures.test.ts also validates them against the JSON Schemas in /schemas.
 * Synthetic data only: no real people.
 */
import type {
  GapAnalysis,
  InterviewType,
  JobPosting,
  PlannedSession,
  Resume,
  Scorecard,
} from "../api/types";

export const jobPosting: JobPosting = {
  company_name: "Stripe",
  title: "Senior Software Engineer, Payments Reliability",
  role_family: "swe",
  level: "senior",
  level_label: "L3",
  team: "Payments Reliability",
  location: "Seattle, WA (hybrid)",
  must_have_skills: ["Python or Go", "Distributed systems", "PostgreSQL", "On-call ownership"],
  nice_to_have_skills: ["Payments domain", "Kafka"],
  responsibilities: [
    "Design and run services that move money safely",
    "Lead technical design reviews for the team",
    "Reduce incident rate for the card authorization path",
  ],
  source_url: "https://example-board.test/jobs/1234",
};

export const resume: Resume = {
  summary: "Backend engineer with 7 years in billing and payments systems.",
  roles: [
    {
      title: "Software Engineer II",
      company: "Shoply",
      start: "2021-03",
      end: null,
      achievements: [
        "Built the refunds API used by 40,000 merchants",
        "Led migration of 30 services to PostgreSQL 15 with zero downtime",
      ],
      skills: ["Python", "PostgreSQL", "Kafka"],
    },
    {
      title: "Software Engineer",
      company: "Invoicely",
      start: "2018-06",
      end: "2021-02",
      achievements: ["Cut nightly invoice job runtime from 4 hours to 25 minutes"],
      skills: ["Python", "Celery"],
    },
  ],
  skills: ["Python", "Go", "PostgreSQL", "Kafka", "AWS"],
  education: [
    { institution: "State University", degree: "BSc", field_of_study: "Computer Science", end: "2018" },
  ],
  certifications: [],
};

export const sessionPlan: PlannedSession[] = [
  {
    priority: 1,
    interview_type: "behavioral",
    difficulty: "realistic",
    focus_topics: ["Leading without authority", "Cross-team design reviews"],
    reason: "The largest gap is scope at senior level.",
  },
  {
    priority: 2,
    interview_type: "technical_qa",
    difficulty: "realistic",
    focus_topics: ["Idempotency", "Exactly-once payments"],
    reason: "Core to the role and only partly shown on the resume.",
  },
  {
    priority: 3,
    interview_type: "hiring_manager",
    difficulty: "tough",
    focus_topics: ["Incident ownership", "Why this team"],
    reason: "The posting asks for on-call ownership.",
  },
];

export const gapAnalysis: GapAnalysis = {
  match_score: 72,
  requirement_breakdown: [
    { requirement: "Python or Go", kind: "must_have", score: 95, evidence: "7 years of Python in billing systems" },
    { requirement: "Distributed systems", kind: "must_have", score: 60, evidence: "Partitioned invoice jobs across workers" },
    { requirement: "PostgreSQL", kind: "must_have", score: 90, evidence: "Led migration of 30 services to PostgreSQL 15" },
    { requirement: "On-call ownership", kind: "must_have", score: 45, evidence: null },
    { requirement: "Payments domain", kind: "nice_to_have", score: 80, evidence: "Built the refunds API at Shoply" },
    { requirement: "Kafka", kind: "nice_to_have", score: 70, evidence: "Kafka listed for the Shoply role" },
  ],
  competency_breakdown: [
    { competency: "technical_depth", score: 75, notes: null },
    { competency: "ownership", score: 70, notes: null },
    { competency: "scope_at_level", score: 55, notes: "Little evidence of cross-team leadership" },
    { competency: "communication", score: 65, notes: null },
  ],
  strengths: [
    { summary: "Strong PostgreSQL operations", evidence: "Led migration of 30 services to PostgreSQL 15 with zero downtime" },
    { summary: "Payments experience", evidence: "Built the refunds API used by 40,000 merchants" },
  ],
  gaps: [
    { summary: "No clear technical leadership across teams", severity: "high", related_requirement: "Lead technical design reviews for the team" },
    { summary: "No incident or on-call examples", severity: "medium", related_requirement: "On-call ownership" },
    { summary: "Distributed systems depth is unclear", severity: "low", related_requirement: "Distributed systems" },
  ],
  probe_areas: ["Design review leadership", "Failure handling in money movement", "Incident response"],
  session_plan: sessionPlan,
};

const behavioralScorecard: Scorecard = {
  hire_signal: "Lean Hire",
  rationale:
    "The candidate showed clear ownership of the invoice migration and gave a measurable result. Collaboration examples were thin and mostly within one team. At senior level we expect cross-team influence, which was not shown. The signal is Lean Hire.",
  competency_scores: [
    { competency: "ownership", score: 3, justification: "Owned the migration plan and rollout.", quotes: ["I wrote the plan and ran the cutover myself."] },
    { competency: "impact", score: 3, justification: "Gave a measurable result.", quotes: ["Runtime went from four hours to twenty-five minutes."] },
    { competency: "collaboration", score: 2, justification: "Examples stayed inside one team.", quotes: ["My team handled all of it."] },
    { competency: "communication", score: 3, justification: "Clear structure in most answers.", quotes: ["There were three parts to the problem."] },
  ],
  per_question: [
    {
      question_ref: "q1",
      question_text: "Tell me about a project you owned end to end.",
      scores: [
        { competency: "ownership", score: 3, justification: "Clear personal role.", quotes: ["I wrote the plan and ran the cutover myself."] },
        { competency: "impact", score: 3, justification: "Quantified result.", quotes: ["Runtime went from four hours to twenty-five minutes."] },
      ],
      strengths: ["Measurable result: runtime down from 4 hours to 25 minutes"],
      misses: ["Did not explain the trade-offs considered"],
    },
    {
      question_ref: "q2",
      question_text: "Tell me about a time you disagreed with another team.",
      scores: [
        { competency: "collaboration", score: 2, justification: "No other team was involved in the example.", quotes: ["My team handled all of it."] },
      ],
      strengths: ["Stayed calm and specific"],
      misses: ["The example did not involve another team", "No outcome for the relationship"],
    },
  ],
  scorer_model: "fake-scorer",
  rubric_version: "scorer/rubric.v1",
};

const technicalScorecard: Scorecard = {
  hire_signal: "Hire",
  rationale:
    "The candidate explained idempotency keys and retries correctly and named the trade-offs. Answers on exactly-once delivery were accurate for the level. Reasoning was clear and structured. The signal is Hire.",
  competency_scores: [
    { competency: "technical_depth", score: 3, justification: "Correct model of idempotent writes.", quotes: ["The key is stored with the result, so a retry returns the same answer."] },
    { competency: "trade_offs", score: 3, justification: "Named storage cost of keys.", quotes: ["We keep keys for a day, which costs storage."] },
    { competency: "reasoning", score: 4, justification: "Built the answer step by step.", quotes: ["First I would ask what failure we are protecting against."] },
  ],
  per_question: [
    {
      question_ref: "t1",
      question_text: "How would you make a payment API safe to retry?",
      scores: [
        { competency: "technical_depth", score: 3, justification: "Correct approach.", quotes: ["The key is stored with the result, so a retry returns the same answer."] },
      ],
      strengths: ["Correct use of idempotency keys"],
      misses: ["Did not mention key expiry until asked"],
    },
  ],
  scorer_model: "fake-scorer",
  rubric_version: "scorer/rubric.v1",
};

export function scorecardFor(type: InterviewType): Scorecard {
  return type === "technical_qa" ? technicalScorecard : behavioralScorecard;
}
