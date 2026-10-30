/**
 * U08: the MSW handlers return one suggestion of every kind (SG-1) in the API's shape, list them
 * by place, and accept, dismiss and undo them like the API (SG-8).
 */
import { describe, expect, it } from "vitest";

import type { Suggestion, SuggestionAcceptOut } from "../api/types";
import { sampleSuggestions } from "./suggestionHandlers";

const api = (path: string, init?: RequestInit) => fetch(`${location.origin}/api${path}`, init);
const post = (path: string, body: unknown = {}) =>
  api(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

describe("suggestion mocks", () => {
  it("SG-1: there is one sample of every kind, its payload kind matching", () => {
    const kinds = sampleSuggestions().map((s) => s.kind);
    expect(new Set(kinds)).toEqual(
      new Set(["tune_story", "new_story", "missing_skill", "tailor_role", "improve_resume_line", "story_idea", "review"]),
    );
    for (const s of sampleSuggestions()) expect(s.payload.kind).toBe(s.kind);
  });

  it("SG-8: list by place; accept and dismiss take one out; undo puts it back", async () => {
    const list = async (q: string) => ((await (await api(`/suggestions?${q}`)).json()) as Suggestion[]).map((s) => s.kind);
    expect(await list("place=debrief&session_id=s1")).toEqual(["tune_story", "new_story", "missing_skill"]);
    expect(await list("place=resume&resume_id=r1")).toEqual(["improve_resume_line", "story_idea"]);
    expect((await api("/suggestions?place=nowhere")).status).toBe(422);

    const [tune, , missing] = sampleSuggestions();
    const accepted = (await (await post(`/suggestions/${tune.id}/accept`)).json()) as SuggestionAcceptOut;
    expect(accepted.suggestion.status).toBe("accepted");
    expect(accepted.can_undo).toBe(true);
    expect((await post(`/suggestions/${tune.id}/accept`)).status).toBe(409);
    expect(await list("place=story&story_id=11111111-1111-4111-8111-111111111111")).toEqual(["tailor_role"]);
    expect(((await (await post(`/suggestions/${tune.id}/undo`)).json()) as Suggestion).status).toBe("open");

    const crafting = (await (await post(`/suggestions/${missing.id}/accept`)).json()) as SuggestionAcceptOut;
    expect(crafting.crafting?.competency).toBe("conflict_handling");
    const dismissed = (await (await post(`/suggestions/${sampleSuggestions()[3].id}/dismiss`)).json()) as Suggestion;
    expect(dismissed.status).toBe("dismissed");
    expect(await list("place=role&job_target_id=j1")).toEqual([]);
  });
});
