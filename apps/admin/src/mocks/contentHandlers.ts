/**
 * MSW handlers for the Content routes (AT-1..AT-5), with the same paths and shapes as
 * openapi.json. The mock keeps a small company list, profile versions and company requests per
 * mock database. Its import check is a stand-in for the real schema check: invalid JSON and a few
 * missing required fields give the same `invalid_profile` error shape as the API.
 */
import { http, HttpResponse } from "msw/http";

import type {
  AdminCompany,
  CompanyProfiles,
  CompanyRequestGroup,
  DiffChange,
  ProfileDiff,
  ProfileImportIn,
  ProfileImportOut,
  ProfileStatus,
  ProfileVersion,
  ProfileVersionDetail,
  TransitionOut,
  TransitionTo,
  TriageIn,
} from "../api/content";
import { NEXT_STATUSES } from "../api/content";
import type { MockDb, MockStore } from "./db";
import { API, isMockAdmin } from "./handlers";

interface MockVersion {
  version: number;
  status: ProfileStatus;
  imported_at: string;
  published_at: string | null;
  reviewed_by: string | null;
  profile: Record<string, unknown>;
}

interface MockCompany {
  id: string;
  slug: string;
  name: string;
  active: boolean;
  request_users: number;
  versions: MockVersion[];
}

interface ContentState {
  companies: MockCompany[];
  requests: CompanyRequestGroup[];
}

const REQUIRED = ["company_slug", "company_name", "values_framework", "persona", "sources", "meta"];

export function mockProfile(slug: string, name: string, pace: string): Record<string, unknown> {
  return {
    company_slug: slug,
    company_name: name,
    values_framework: { name: `${name} values`, principles: [{ name: "Customers first", description: "Start with the user" }] },
    persona: { tone: "Direct", pace, pushback_style: "Asks for numbers", closing_style: "Leaves time" },
    sources: [
      { url: `https://${slug}.example.com/careers`, title: `${name} careers`, retrieved_at: "2026-10-01", fields: ["persona"] },
    ],
    meta: { version: 1, status: "draft", reviewed_by: null, researched_at: "2026-10-01", published_at: null },
  };
}

function seedContent(): ContentState {
  return {
    companies: [
      {
        id: "00000000-0000-4000-8000-0000000000e1",
        slug: "example-corp",
        name: "Example Corp",
        active: true,
        request_users: 3,
        versions: [
          {
            version: 1,
            status: "published",
            imported_at: "2026-10-02T09:00:00Z",
            published_at: "2026-10-03T09:00:00Z",
            reviewed_by: "admin@example.com",
            profile: mockProfile("example-corp", "Example Corp", "Moderate"),
          },
          {
            version: 2,
            status: "draft",
            imported_at: "2026-10-10T09:00:00Z",
            published_at: null,
            reviewed_by: null,
            profile: mockProfile("example-corp", "Example Corp", "Fast"),
          },
        ],
      },
      {
        id: "00000000-0000-4000-8000-0000000000e2",
        slug: "google",
        name: "Google",
        active: true,
        request_users: 0,
        versions: [],
      },
    ],
    requests: [
      {
        normalized_name: "acme",
        names: ["Acme Inc.", "ACME"],
        users: 2,
        requests: 3,
        first_requested: "2026-10-01T09:00:00Z",
        last_requested: "2026-10-04T09:00:00Z",
        source_hosts: ["boards.greenhouse.io"],
        triage: { state: "new", company_id: null, company_slug: null, note: null, updated_by: null, updated_at: null },
      },
    ],
  };
}

const states = new WeakMap<MockDb, ContentState>();

export function contentState(db: MockDb): ContentState {
  let state = states.get(db);
  if (!state) {
    state = seedContent();
    states.set(db, state);
  }
  return state;
}

const notFound = (detail = "Not Found") => HttpResponse.json({ detail }, { status: 404 });

function flatten(value: unknown, prefix = "", out: Record<string, unknown> = {}): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length) {
    for (const [k, v] of Object.entries(value)) {
      if (!prefix && k === "meta") continue;
      flatten(v, prefix ? `${prefix}.${k}` : k, out);
    }
  } else if (Array.isArray(value) && value.length) {
    value.forEach((v, i) => flatten(v, `${prefix}[${i}]`, out));
  } else {
    out[prefix] = value;
  }
  return out;
}

function diff(a: number | null, old: Record<string, unknown> | null, b: number, next: Record<string, unknown>): ProfileDiff {
  const before = flatten(old ?? {});
  delete before[""];
  const after = flatten(next);
  const changes: DiffChange[] = [];
  for (const [path, value] of Object.entries(after)) {
    if (!(path in before)) changes.push({ path, kind: "added", old: null, new: value });
    else if (JSON.stringify(before[path]) !== JSON.stringify(value))
      changes.push({ path, kind: "changed", old: before[path], new: value });
  }
  for (const [path, value] of Object.entries(before)) {
    if (!(path in after)) changes.push({ path, kind: "removed", old: value, new: null });
  }
  const fields = REQUIRED.filter((f) => f !== "meta");
  return {
    a,
    b,
    total: changes.length,
    fields: fields.map((field) => ({
      field,
      changes: changes.filter((c) => c.path.split(/[.[]/)[0] === field),
    })),
  };
}

function versionOut(v: MockVersion): ProfileVersion {
  const sources = (v.profile.sources as unknown[] | undefined) ?? [];
  return {
    version: v.version,
    status: v.status,
    imported_at: v.imported_at,
    published_at: v.published_at,
    reviewed_by: v.reviewed_by,
    source_count: sources.length,
  };
}

function companyOut(c: MockCompany): AdminCompany {
  const published = c.versions.find((v) => v.status === "published");
  return {
    id: c.id,
    slug: c.slug,
    name: c.name,
    active: c.active,
    published_version: published?.version ?? null,
    latest_version: c.versions.at(-1)?.version ?? null,
    version_count: c.versions.length,
    draft_count: c.versions.filter((v) => v.status === "draft").length,
    in_review_count: c.versions.filter((v) => v.status === "in_review").length,
    request_users: c.request_users,
  };
}

function invalid(message: string, problems: string[], code = "invalid_profile") {
  return HttpResponse.json({ detail: { code, message, problems } }, { status: 422 });
}

export function contentHandlers(store: MockStore) {
  const admin = () => {
    const { auth } = store.db;
    return auth.status === "signed_in" && auth.userEmail && isMockAdmin(auth.userEmail) ? auth.userEmail : null;
  };
  const state = () => contentState(store.db);
  const company = (slug: unknown) => state().companies.find((c) => c.slug === slug);
  const write = (request: Request) => request.headers.get("X-Admin-Request") === "1";

  return [
    http.get(`${API}/admin/companies`, () => {
      if (!admin()) return notFound();
      const rows = [...state().companies].sort((x, y) => x.name.localeCompare(y.name));
      return HttpResponse.json(rows.map(companyOut));
    }),
    http.patch(`${API}/admin/companies/:slug`, async ({ params, request }) => {
      if (!admin()) return notFound();
      if (!write(request)) return HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
      const c = company(params.slug);
      if (!c) return notFound("Company not found");
      const body = (await request.json()) as { active: boolean };
      c.active = body.active;
      return HttpResponse.json(companyOut(c));
    }),
    http.get(`${API}/admin/companies/:slug/profiles`, ({ params }) => {
      if (!admin()) return notFound();
      const c = company(params.slug);
      if (!c) return notFound("Company not found");
      const body: CompanyProfiles = { company: companyOut(c), versions: c.versions.map(versionOut) };
      return HttpResponse.json(body);
    }),
    http.get(`${API}/admin/companies/:slug/profiles/diff`, ({ params, request }) => {
      if (!admin()) return notFound();
      const c = company(params.slug);
      const q = new URL(request.url).searchParams;
      const a = c?.versions.find((v) => v.version === Number(q.get("a")));
      const b = c?.versions.find((v) => v.version === Number(q.get("b")));
      if (!c || !a || !b) return notFound("No such version");
      return HttpResponse.json(diff(a.version, a.profile, b.version, b.profile));
    }),
    http.get(`${API}/admin/companies/:slug/profiles/:version`, ({ params }) => {
      if (!admin()) return notFound();
      const v = company(params.slug)?.versions.find((x) => x.version === Number(params.version));
      if (!v) return notFound("No such version");
      const body: ProfileVersionDetail = {
        ...versionOut(v),
        profile: v.profile,
        sources: (v.profile.sources as unknown[]) ?? [],
        problems: [],
      };
      return HttpResponse.json(body);
    }),
    http.post(`${API}/admin/companies/:slug/profiles`, async ({ params, request }) => {
      if (!admin()) return notFound();
      if (!write(request)) return HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
      const body = (await request.json()) as ProfileImportIn;
      let data: Record<string, unknown>;
      try {
        data = (body.profile ?? JSON.parse(body.profile_text ?? "")) as Record<string, unknown>;
      } catch {
        return invalid("The profile does not match the company profile schema.", [
          "not valid JSON: Expecting value at line 1, column 1",
        ]);
      }
      const missing = REQUIRED.filter((f) => !(f in data)).map((f) => `${f}: Field required`);
      if (missing.length) return invalid("The profile does not match the company profile schema.", missing);
      if (data.company_slug !== params.slug) {
        return invalid(`The file is for '${String(data.company_slug)}', not '${String(params.slug)}'.`, [], "slug_mismatch");
      }
      let c = company(params.slug);
      let created = false;
      if (!c) {
        if (!body.create_company) {
          return HttpResponse.json(
            { detail: { code: "unknown_company", message: `'${String(params.slug)}' is not a company yet.` } },
            { status: 404 },
          );
        }
        c = { id: crypto.randomUUID(), slug: String(params.slug), name: String(data.company_name), active: false, request_users: 0, versions: [] };
        state().companies.push(c);
        created = true;
      }
      const latest = c.versions.at(-1);
      if (latest && !body.force && diff(null, latest.profile, 0, data).total === 0) {
        return HttpResponse.json(
          { detail: { code: "unchanged", message: `The file has the same content as version ${latest.version}.` } },
          { status: 409 },
        );
      }
      const v: MockVersion = {
        version: (latest?.version ?? 0) + 1,
        status: "draft",
        imported_at: new Date().toISOString(),
        published_at: null,
        reviewed_by: null,
        profile: data,
      };
      c.versions.push(v);
      const published = c.versions.find((x) => x.status === "published");
      const out: ProfileImportOut = {
        company: companyOut(c),
        version: versionOut(v),
        company_created: created,
        file_version: 1,
        summary: [`Company: ${c.name} (${c.slug})`],
        diff: diff(published?.version ?? null, published?.profile ?? null, v.version, data),
      };
      return HttpResponse.json(out, { status: 201 });
    }),
    http.post(`${API}/admin/companies/:slug/profiles/:version/transition`, async ({ params, request }) => {
      const who = admin();
      if (!who) return notFound();
      if (!write(request)) return HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
      const c = company(params.slug);
      const v = c?.versions.find((x) => x.version === Number(params.version));
      if (!c || !v) return notFound("No such version");
      const { to } = (await request.json()) as { to: TransitionTo };
      if (!NEXT_STATUSES[v.status].includes(to)) {
        return HttpResponse.json(
          { detail: { code: "transition_not_allowed", message: `Version ${v.version} is ${v.status}.` } },
          { status: 409 },
        );
      }
      const from = v.status;
      let archived: number | null = null;
      if (to === "published") {
        const live = c.versions.find((x) => x.status === "published");
        if (live) {
          live.status = "archived";
          archived = live.version;
        }
        v.published_at = new Date().toISOString();
        v.reviewed_by = who;
      }
      v.status = to;
      const out: TransitionOut = { version: versionOut(v), from_status: from, archived_version: archived };
      return HttpResponse.json(out);
    }),
    http.get(`${API}/admin/company-requests`, ({ request }) => {
      if (!admin()) return notFound();
      const filter = new URL(request.url).searchParams.get("state");
      return HttpResponse.json(state().requests.filter((g) => !filter || g.triage.state === filter));
    }),
    http.put(`${API}/admin/company-requests/:name/triage`, async ({ params, request }) => {
      const who = admin();
      if (!who) return notFound();
      if (!write(request)) return HttpResponse.json({ detail: "X-Admin-Request: 1 is required" }, { status: 403 });
      const g = state().requests.find((x) => x.normalized_name === params.name);
      if (!g) return notFound("No unmatched requests with this name");
      const body = (await request.json()) as TriageIn;
      const linked = state().companies.find((c) => c.id === body.company_id);
      g.triage = {
        state: body.state,
        company_id: body.company_id ?? null,
        company_slug: linked?.slug ?? null,
        note: body.note ?? null,
        updated_by: who,
        updated_at: new Date().toISOString(),
      };
      return HttpResponse.json(g);
    }),
  ];
}
