/**
 * Content (AT-1..AT-5): companies, profile versions (view, diff, import, workflow) and the company
 * request backlog. Writes send `X-Admin-Request: 1` and a reason (AA-5, AA-6).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

type S = components["schemas"];

export type AdminCompany = S["AdminCompany"];
export type CompanyProfiles = S["CompanyProfiles"];
export type ProfileVersion = S["ProfileVersion"];
export type ProfileVersionDetail = S["ProfileVersionDetail"];
export type ProfileDiff = S["ProfileDiff"];
export type DiffField = S["DiffField"];
export type DiffChange = S["DiffChange"];
export type ProfileImportIn = S["ProfileImportIn"];
export type ProfileImportOut = S["ProfileImportOut"];
export type ProfileStatus = S["ProfileStatus"];
export type TransitionTo = S["TransitionIn"]["to"];
export type TransitionOut = S["TransitionOut"];
export type CompanyRequestGroup = S["CompanyRequestGroup"];
export type TriageState = S["TriageState"];
export type TriageIn = S["TriageIn"];

const WRITE = { headers: { "X-Admin-Request": "1" } };

/** The workflow (AT-4). The API checks it too; this decides which buttons to show. */
export const NEXT_STATUSES: Record<ProfileStatus, TransitionTo[]> = {
  draft: ["in_review"],
  in_review: ["published", "draft"],
  published: ["archived"],
  archived: ["published"],
};

/** The problems list of a failed import (AT-3), or null for other errors. */
export function importProblems(error: unknown): string[] | null {
  if (!(error instanceof ApiError)) return null;
  const detail = error.detail as { problems?: unknown } | null;
  return detail && Array.isArray(detail.problems) ? detail.problems.map(String) : null;
}

export const contentApi = {
  companies: async () => unwrap(await apiClient.GET("/admin/companies")),
  setActive: async (slug: string, active: boolean, reason: string) =>
    unwrap(
      await apiClient.PATCH("/admin/companies/{slug}", {
        params: { path: { slug } },
        body: { active, reason },
        ...WRITE,
      }),
    ),
  profiles: async (slug: string) =>
    unwrap(await apiClient.GET("/admin/companies/{slug}/profiles", { params: { path: { slug } } })),
  version: async (slug: string, version: number) =>
    unwrap(
      await apiClient.GET("/admin/companies/{slug}/profiles/{version}", {
        params: { path: { slug, version } },
      }),
    ),
  diff: async (slug: string, a: number, b: number) =>
    unwrap(
      await apiClient.GET("/admin/companies/{slug}/profiles/diff", {
        params: { path: { slug }, query: { a, b } },
      }),
    ),
  importProfile: async (slug: string, body: ProfileImportIn) =>
    unwrap(
      await apiClient.POST("/admin/companies/{slug}/profiles", {
        params: { path: { slug } },
        body,
        ...WRITE,
      }),
    ),
  transition: async (slug: string, version: number, to: TransitionTo, reason: string) =>
    unwrap(
      await apiClient.POST("/admin/companies/{slug}/profiles/{version}/transition", {
        params: { path: { slug, version } },
        body: { to, reason },
        ...WRITE,
      }),
    ),
  requests: async (state?: TriageState) =>
    unwrap(await apiClient.GET("/admin/company-requests", { params: { query: state ? { state } : {} } })),
  triage: async (normalizedName: string, body: TriageIn) =>
    unwrap(
      await apiClient.PUT("/admin/company-requests/{normalized_name}/triage", {
        params: { path: { normalized_name: normalizedName } },
        body,
        ...WRITE,
      }),
    ),
};

export const contentKeys = {
  all: ["admin", "content"] as const,
  companies: ["admin", "content", "companies"] as const,
  profiles: (slug: string) => ["admin", "content", "profiles", slug] as const,
  version: (slug: string, version: number) => ["admin", "content", "version", slug, version] as const,
  diff: (slug: string, a: number, b: number) => ["admin", "content", "diff", slug, a, b] as const,
  requests: (state?: TriageState) => ["admin", "content", "requests", state ?? "all"] as const,
};

export const useCompanies = () => useQuery({ queryKey: contentKeys.companies, queryFn: contentApi.companies });

export const useCompanyProfiles = (slug: string) =>
  useQuery({ queryKey: contentKeys.profiles(slug), queryFn: () => contentApi.profiles(slug) });

export const useProfileVersion = (slug: string, version: number | null) =>
  useQuery({
    queryKey: contentKeys.version(slug, version ?? 0),
    queryFn: () => contentApi.version(slug, version ?? 0),
    enabled: version !== null,
  });

export const useProfileDiff = (slug: string, a: number | null, b: number | null) =>
  useQuery({
    queryKey: contentKeys.diff(slug, a ?? 0, b ?? 0),
    queryFn: () => contentApi.diff(slug, a ?? 0, b ?? 0),
    enabled: a !== null && b !== null && a !== b,
  });

export const useCompanyRequests = (state?: TriageState) =>
  useQuery({ queryKey: contentKeys.requests(state), queryFn: () => contentApi.requests(state) });

/** Every content write changes counts on several pages, so it refreshes all content queries. */
function useContentMutation<A, R>(fn: (args: A) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: contentKeys.all }),
  });
}

export const useSetCompanyActive = () =>
  useContentMutation((a: { slug: string; active: boolean; reason: string }) =>
    contentApi.setActive(a.slug, a.active, a.reason),
  );

export const useImportProfile = () =>
  useContentMutation((a: { slug: string; body: ProfileImportIn }) => contentApi.importProfile(a.slug, a.body));

export const useTransition = () =>
  useContentMutation((a: { slug: string; version: number; to: TransitionTo; reason: string }) =>
    contentApi.transition(a.slug, a.version, a.to, a.reason),
  );

export const useTriage = () =>
  useContentMutation((a: { name: string; body: TriageIn }) => contentApi.triage(a.name, a.body));
