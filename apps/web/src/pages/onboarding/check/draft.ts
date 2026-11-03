/**
 * The resume as the check page edits it (IN-3): the draft, its validation and the Resume contract
 * built from it. `ResumeCheckV2` owns the state; the steps read and change it through callbacks.
 */
import type { Resume } from "../../../api/types";
import { newestFirst } from "../resumeChecks";

export type Education = Resume["education"][number];

/** One role as the page edits it. Dates are text; an empty end means the current role. */
export interface CvRole {
  key: number;
  company: string;
  title: string;
  start: string;
  end: string;
  achievements: string[];
  skills: string[];
}

export interface CvDraft {
  summary: string;
  roles: CvRole[];
  skills: string[];
  education: Education[];
  certifications: string[];
}

export type RoleErrors = Partial<Record<"company" | "title" | "start" | "end", string>>;

export const DATE = /^\d{4}(-(0[1-9]|1[0-2]))?$/;
/** Roles after this many show as one line until opened. */
export const OPEN_ROLES = 2;

let nextKey = 1;
export const newKey = () => nextKey++;

export function toCvDraft(resume: Resume): CvDraft {
  return {
    summary: resume.summary ?? "",
    roles: newestFirst(resume.roles).map((r) => ({
      key: newKey(),
      company: r.company,
      title: r.title,
      start: r.start ?? "",
      end: r.end ?? "",
      achievements: [...r.achievements],
      skills: [...r.skills],
    })),
    skills: [...resume.skills],
    education: resume.education.map((e) => ({ ...e })),
    certifications: [...resume.certifications],
  };
}

export function validateRole(role: CvRole): RoleErrors {
  const errors: RoleErrors = {};
  if (!role.company.trim()) errors.company = "Enter the company.";
  if (!role.title.trim()) errors.title = "Enter the job title.";
  for (const name of ["start", "end"] as const) {
    const value = role[name].trim();
    if (value && !DATE.test(value)) errors[name] = "Use YYYY or YYYY-MM, for example 2021-03.";
  }
  return errors;
}

export const cleanList = (items: string[]) => [...new Set(items.map((s) => s.trim()).filter(Boolean))];

/** The Resume contract built from the draft. Call after every role passes `validateRole`. */
export function cvDraftToResume(draft: CvDraft): Resume {
  return {
    summary: draft.summary.trim() || null,
    roles: draft.roles.map((r) => ({
      company: r.company.trim(),
      title: r.title.trim(),
      start: r.start.trim() || null,
      end: r.end.trim() || null,
      achievements: r.achievements.map((a) => a.trim()).filter(Boolean),
      skills: cleanList(r.skills),
    })),
    skills: cleanList(draft.skills),
    education: draft.education
      .filter((e) => e.institution.trim())
      .map((e) => ({
        institution: e.institution.trim(),
        degree: e.degree?.trim() || null,
        field_of_study: e.field_of_study?.trim() || null,
        end: e.end?.trim() && DATE.test(e.end.trim()) ? e.end.trim() : null,
      })),
    certifications: cleanList(draft.certifications),
  };
}

/** The draft as the checks read it: like `cvDraftToResume`, but it keeps empty and odd values. */
export function forChecks(draft: CvDraft): Resume {
  return {
    ...cvDraftToResume(draft),
    roles: draft.roles.map((r) => ({
      company: r.company,
      title: r.title,
      start: r.start.trim() || null,
      end: r.end.trim() || null,
      achievements: r.achievements,
      skills: r.skills,
    })),
  };
}

/** A copy of `record` without `key`. */
export function omit<T>(record: Record<number, T>, key: number): Record<number, T> {
  const next = { ...record };
  delete next[key];
  return next;
}

/** A copy of `set` without `key`. */
export function without<T>(set: ReadonlySet<T>, key: T): ReadonlySet<T> {
  if (!set.has(key)) return set;
  const next = new Set(set);
  next.delete(key);
  return next;
}

export const splitList = (text: string, by: RegExp) => text.split(by).map((s) => s.trim()).filter(Boolean);
