/**
 * Q13: interview guides, one per company and role. A guide is built only when its company is in
 * GUIDES_PUBLISHED and the profile in profiles/<slug>.json has a reviewer (L02). Today none are,
 * so no guide pages exist. Content comes only from the profile, in our own words.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

/** Add a company slug here once its profile is reviewed and published on the server. */
export const GUIDES_PUBLISHED: string[] = [];

export const ROLE_LABELS: Record<string, string> = {
  swe: "software engineer",
  infra_security: "infrastructure and security engineer",
  data_ml: "data science and ML",
  data_analytics: "data analyst",
  pm: "product manager",
  design: "designer",
  tpm: "technical program manager",
  eng_management: "engineering manager",
  finance: "finance",
  consulting_strategy: "consulting and strategy",
  project_program: "project and program manager",
};

const TYPE_LABELS: Record<string, string> = {
  behavioral: "Behavioral",
  technical_qa: "Technical questions",
  case: "Case",
  hiring_manager: "Hiring manager",
};

export interface Guide {
  company: string;
  slug: string;
  role: string;
  roleLabel: string;
  values: { name: string; description: string }[];
  valuesName: string | null;
  rounds: { name: string; minutes: number | null; who: string; notes: string }[];
  levels: string[];
  patterns: { type: string; theme: string; pattern: string }[];
}

const PROFILES_DIR = fileURLToPath(new URL("../../../../profiles/", import.meta.url));

interface ProfileJson {
  company_name: string;
  company_slug: string;
  meta: { reviewed_by: string | null };
  values_framework?: { name: string; principles: { name: string; description: string }[] } | null;
  loop_structure: {
    role_family: string;
    levels: string[];
    rounds: { name: string; duration_min: number | null; interviewer_role: string; notes: string }[];
  }[];
  question_patterns: { interview_type: string; theme: string; pattern: string; role_families?: string[] }[];
}

export function loadGuides(published: string[] = GUIDES_PUBLISHED, dir: string = PROFILES_DIR): Guide[] {
  const guides: Guide[] = [];
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".json")).sort()) {
    const p = JSON.parse(readFileSync(join(dir, file), "utf8")) as ProfileJson;
    if (!published.includes(p.company_slug) || !p.meta.reviewed_by) continue;
    for (const loop of p.loop_structure) {
      if (!(loop.role_family in ROLE_LABELS)) continue;
      guides.push({
        company: p.company_name,
        slug: p.company_slug,
        role: loop.role_family,
        roleLabel: ROLE_LABELS[loop.role_family],
        valuesName: p.values_framework?.name ?? null,
        values: (p.values_framework?.principles ?? []).map((v) => ({ name: v.name, description: v.description })),
        rounds: loop.rounds.map((r) => ({
          name: r.name,
          minutes: r.duration_min,
          who: r.interviewer_role,
          notes: r.notes,
        })),
        levels: loop.levels,
        patterns: p.question_patterns
          .filter((q) => !q.role_families || q.role_families.includes(loop.role_family))
          .slice(0, 8)
          .map((q) => ({ type: TYPE_LABELS[q.interview_type] ?? q.interview_type, theme: q.theme, pattern: q.pattern })),
      });
    }
  }
  return guides;
}
