/**
 * Q13: interview guides, one page per published company profile and role (21 x 5 at most).
 * A guide appears only once its profile's meta.status is "published". Today none are, so the
 * template ships and no guide pages are built.
 */

export type RoleFamily = "swe" | "data_ml" | "pm" | "design" | "tpm";

export const ROLE_LABEL: Record<RoleFamily, string> = {
  swe: "Software engineer",
  data_ml: "Data and ML",
  pm: "Product manager",
  design: "Designer",
  tpm: "Technical program manager",
};

export const ROLE_SLUG: Record<RoleFamily, string> = {
  swe: "software-engineer",
  data_ml: "data-ml",
  pm: "product-manager",
  design: "designer",
  tpm: "technical-program-manager",
};

interface Round {
  name: string;
  interview_type: string | null;
  duration_min: number | null;
  interviewer_role: string | null;
  notes: string | null;
}

export interface Profile {
  company_name: string;
  company_slug: string;
  meta: { status: string; published_at: string | null };
  values_framework?: { name: string; principles: { name: string; description: string }[] } | null;
  loop_structure: { role_family: RoleFamily; levels: string[]; rounds: Round[] }[];
  question_patterns?: { interview_type: string; theme: string; pattern: string }[];
  bar_by_level?: { level_name: string; role_family: RoleFamily; scope_expectation: string }[];
  persona?: { tone: string; pace: string; pushback_style: string; closing_style: string };
}

const files = import.meta.glob<Profile>("../../../../profiles/*.json", { eager: true, import: "default" });

export function allProfiles(): Profile[] {
  return Object.values(files).filter((p) => p && typeof p === "object" && "company_slug" in p);
}

export interface Guide {
  profile: Profile;
  role: RoleFamily;
  companySlug: string;
  roleSlug: string;
}

export function publishedGuides(): Guide[] {
  const out: Guide[] = [];
  for (const profile of allProfiles()) {
    if (profile.meta?.status !== "published") continue;
    for (const loop of profile.loop_structure ?? []) {
      if (!(loop.role_family in ROLE_SLUG)) continue;
      out.push({ profile, role: loop.role_family, companySlug: profile.company_slug, roleSlug: ROLE_SLUG[loop.role_family] });
    }
  }
  return out.sort((a, b) => a.profile.company_name.localeCompare(b.profile.company_name));
}

export const INTERVIEW_TYPE_LABEL: Record<string, string> = {
  behavioral: "Behavioral",
  hiring_manager: "Hiring manager deep dive",
  technical_qa: "Verbal technical Q&A",
  case: "Case",
};
