/**
 * MSW handlers for the Questions page (QB-1 to QB-3), with the shapes in openapi.json. The
 * filtering mirrors apps/api strong_api.questions so the mock behaves like the real endpoint.
 */
import { http, HttpResponse } from "msw/http";

import type { BankCompany, BankQuestion, QuestionList } from "../api/types";

const API = "*/api";

function hints(focus: string) {
  return {
    looking_for: [`How you handle ${focus}`, "Whether you own the outcome"],
    strong_signals: ["A specific story with your own actions", "A measured result"],
    watch_outs: ["A team story with no 'I'", "No clear outcome"],
  };
}

const stripe = { company_slug: "stripe", company_name: "Stripe", source: "company" as const };
const general = { company_slug: null, company_name: null, source: "general" as const, values: [], source_url: null };

export const bankQuestions: BankQuestion[] = [
  {
    ...stripe,
    id: "stripe-1",
    interview_type: "behavioral",
    question: "Tell me about a time you raised the quality bar on something you shipped.",
    competencies: ["ownership", "impact"],
    values: ["Users first"],
    role_families: [],
    levels: [],
    hints: hints("quality"),
    source_url: "https://example.com/stripe-interview",
  },
  {
    ...stripe,
    id: "stripe-2",
    interview_type: "technical_qa",
    question: "How would you design an idempotent payments API?",
    competencies: ["technical_depth", "trade_offs"],
    values: [],
    role_families: ["swe", "tpm"],
    levels: ["senior", "staff_principal"],
    hints: hints("trade-offs"),
    source_url: "https://example.com/stripe-design",
  },
  {
    ...general,
    id: "disagree-with-manager",
    interview_type: "behavioral",
    question: "Tell me about a time you disagreed with your manager.",
    competencies: ["conflict_handling"],
    role_families: [],
    levels: [],
    hints: hints("disagreement"),
  },
  {
    ...general,
    id: "learn-from-failure",
    interview_type: "behavioral",
    question: "Tell me about a project that failed. What did you learn?",
    competencies: ["learning_from_failure"],
    role_families: [],
    levels: [],
    hints: hints("failure"),
  },
  {
    ...general,
    id: "estimate-rides",
    interview_type: "case",
    question: "How many ride-share trips happen in a large city each day?",
    competencies: ["estimation_logic", "structure"],
    role_families: ["pm", "data_ml"],
    levels: [],
    hints: hints("estimation"),
  },
];

export const bankCompanies: BankCompany[] = [{ slug: "stripe", name: "Stripe", question_count: 2 }];

function matches(q: BankQuestion, query: URLSearchParams): boolean {
  const type = query.get("interview_type");
  const areas = query.getAll("competency");
  const role = query.get("role_family");
  const level = query.get("level");
  const text = (query.get("q") ?? "").trim().toLowerCase();
  if (type && q.interview_type !== type) return false;
  if (areas.length && !q.competencies.some((c) => areas.includes(c))) return false;
  if (role && q.role_families.length && !q.role_families.includes(role as never)) return false;
  if (level && q.levels.length && !q.levels.includes(level as never)) return false;
  if (!text) return true;
  const hay = [q.question, ...(q.hints ? Object.values(q.hints).flat() : [])].join(" ").toLowerCase();
  return hay.includes(text);
}

export function questionHandlers() {
  return [
    http.get(`${API}/questions/companies`, () => HttpResponse.json(bankCompanies)),
    http.get(`${API}/questions`, ({ request }) => {
      const query = new URL(request.url).searchParams;
      const company = query.get("company");
      const selected = company && company !== "general" ? bankCompanies.find((c) => c.slug === company) : undefined;
      if (company && company !== "general" && !selected) {
        return HttpResponse.json({ detail: `No published question bank for company '${company}'.` }, { status: 404 });
      }
      const fromCompanies = bankQuestions.filter(
        (q) => q.source === "company" && company !== "general" && (!selected || q.company_slug === selected.slug),
      );
      const body: QuestionList = {
        company: selected ?? null,
        company_questions: fromCompanies.filter((q) => matches(q, query)),
        general_questions: bankQuestions.filter((q) => q.source === "general" && matches(q, query)),
      };
      return HttpResponse.json(body);
    }),
  ];
}
