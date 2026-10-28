/**
 * MSW handler for IN-12: PUT /resumes/{id}/accepted-issues, with the shapes in openapi.json.
 * Like the API: owner only, a live CV, keys of 1 to 200 characters, at most 100 per CV.
 */
import { http, HttpResponse } from "msw/http";

import type { ResumeOut } from "../api/types";
import type { MockStore } from "./db";

const API = "*/api";
const KEY_MAX = 200;
const MAX = 100;

export function acceptedIssuesHandlers(store: MockStore) {
  return [
    http.put(`${API}/resumes/:resumeId/accepted-issues`, async ({ params, request }) => {
      const r: ResumeOut | undefined = store.db.resumes.find((x) => x.id === params.resumeId);
      if (!r || r.deleted) return HttpResponse.json({ detail: "Resume not found" }, { status: 404 });
      const body = (await request.json()) as { key?: unknown; accepted?: unknown };
      const key = typeof body.key === "string" ? body.key.trim() : "";
      if (!key || key.length > KEY_MAX || typeof body.accepted !== "boolean") {
        return HttpResponse.json(
          { detail: [{ type: "value_error", loc: ["body", "key"], msg: "Invalid key", input: body.key }] },
          { status: 422 },
        );
      }
      const current = r.accepted_issues ?? [];
      const old = current.find((i) => i.key === key);
      const rest = current.filter((i) => i.key !== key);
      if (body.accepted) {
        if (rest.length >= MAX) {
          return HttpResponse.json(
            { detail: { code: "accepted_issues_limit", message: `You can accept up to ${MAX} issues on one CV.` } },
            { status: 422 },
          );
        }
        rest.push(old ?? { key, accepted_at: new Date().toISOString() });
      }
      r.accepted_issues = rest;
      store.save();
      return HttpResponse.json(r);
    }),
  ];
}
