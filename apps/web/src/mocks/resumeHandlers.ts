/**
 * MSW handlers for U04, with the shapes in openapi.json: the main resume (RM-2), the API's
 * resume check (RM-5, run with the web check, which has the same rules), story ideas (RM-4) and
 * the plan settings on the profile (PS-2).
 */
import { http, HttpResponse } from "msw/http";

import type { PlanSettingsIn, ResumeIssues, ResumeOut, StoryIdeaCount, StoryIdeaOut, StoryIdeasOut } from "../api/types";
import { parseStoredKey } from "../pages/onboarding/acceptedIssues";
import { checkResume, thisMonth } from "../pages/onboarding/resumeChecks";
import type { MockStore } from "./db";
import { EMPTY_PROFILE } from "./handlers";
import type { StoryRecommendations } from "../pages/stories/api";
import { mockStoryLibrary } from "./storyHandlers";

const API = "*/api";

type Part = StoryIdeaOut["missing_parts"][number];
type Skill = StoryIdeaOut["skills"][number];

const IRREGULAR_PAST = new Set(["led", "built", "ran", "wrote", "drove", "grew", "cut", "made", "took", "won", "set", "began", "rebuilt", "oversaw"]);

/** As strong_worker.inputs.story_ideas.missing_parts: stakes and reflection, and action without a past-tense opener. */
export function missingParts(text: string): Part[] {
  const first = (text.match(/[A-Za-z']+/)?.[0] ?? "").toLowerCase();
  const action = first.endsWith("ed") || IRREGULAR_PAST.has(first) || /\bI\b/.test(text);
  return action ? ["stakes", "reflection"] : ["action", "stakes", "reflection"];
}

/** The mock's stand-in for the skills job: a few keywords. */
function likelySkills(text: string): Skill[] {
  const t = text.toLowerCase();
  const skills: Skill[] = [];
  if (/\b(led|owned|drove|ran)\b/.test(t)) skills.push("ownership");
  if (/\d|%|cut|reduc|grew|increas/.test(t)) skills.push("impact");
  if (/mentor|coach|team|across/.test(t)) skills.push("collaboration");
  if (/migrat|api|latency|service|system|postgres/.test(t)) skills.push("technical_depth");
  return skills.slice(0, 3);
}

const normalize = (text: string) => text.replace(/\s+/g, " ").trim().replace(/[.;]+$/, "").toLowerCase();

const notFound = () => HttpResponse.json({ detail: "Resume not found" }, { status: 404 });
const reading = () =>
  HttpResponse.json({ detail: "The resume is still being read. Try again in a minute." }, { status: 409 });

export function resumeHandlers(store: MockStore) {
  const live = (id: unknown): ResumeOut | undefined => store.db.resumes.find((r) => r.id === id && !r.deleted);
  const dismissed = () => (store.db.storyIdeaDismissed ??= {});
  /** RM-4: one idea per achievement no story uses and not dismissed (the API's rules). */
  const ideasFor = (r: ResumeOut): StoryIdeasOut => {
    const resume = r.resume;
    if (!resume) return { ideas: [], used: [], skills: "ready" };
    const gone = new Set(Object.values(dismissed()).flat()); // CS-3: on every version
    const stories = mockStoryLibrary().filter((s) => !s.deleted_at).map((s) => ({
      story: s,
      text: normalize([s.context, s.stakes, s.action, s.result, s.reflection].filter(Boolean).join(" ")),
    }));
    const body: StoryIdeasOut = { ideas: [], used: [], skills: "ready" };
    resume.roles.forEach((role, i) =>
      role.achievements.forEach((line, j) => {
        const text = line.trim();
        if (!text) return;
        const ref = `roles[${i}].achievements[${j}]`;
        const used = stories.find((s) => s.text.includes(normalize(text)));
        if (used) {
          body.used.push({ achievement: text, resume_line_ref: ref, story_id: used.story.id, story_title: used.story.title });
          return;
        }
        if (gone.has(normalize(text))) return;
        body.ideas.push({
          achievement: text,
          role: `${role.title}, ${role.company}`,
          resume_line_ref: ref,
          skills: likelySkills(text),
          missing_parts: missingParts(text),
        });
      }),
    );
    return body;
  };

  return [
    http.post(`${API}/resumes/:resumeId/main`, ({ params }) => {
      const r = live(params.resumeId);
      if (!r) return notFound();
      for (const other of store.db.resumes) other.is_main = other.id === r.id && !other.deleted;
      store.save();
      return HttpResponse.json(r);
    }),

    http.get(`${API}/resumes/:resumeId/issues`, ({ params, request }) => {
      const r = live(params.resumeId);
      if (!r) return notFound();
      if (!r.resume) return reading();
      const jobId = new URL(request.url).searchParams.get("job_target_id");
      const job = jobId ? store.db.jobs.find((j) => j.id === jobId && !j.deleted) : null;
      if (jobId && !job) return HttpResponse.json({ detail: "Job target not found" }, { status: 404 });
      const stored = new Map((r.accepted_issues ?? []).map((i) => [parseStoredKey(i.key).key, i]));
      const issues = checkResume(r.resume, { today: thisMonth(), job: job?.posting ?? null });
      const body: ResumeIssues = {
        open: issues.filter((i) => !stored.has(i.key)) as ResumeIssues["open"],
        accepted: issues.flatMap((i) => {
          const found = stored.get(i.key);
          return found ? [{ ...i, acceptedAt: found.accepted_at, reason: parseStoredKey(found.key).reason }] : [];
        }) as ResumeIssues["accepted"],
        job_target_id: job?.posting ? job.id : null,
      };
      return HttpResponse.json(body);
    }),

    http.get(`${API}/resumes/:resumeId/story-ideas`, ({ params }) => {
      const r = live(params.resumeId);
      if (!r) return notFound();
      if (!r.resume) return reading();
      return HttpResponse.json(ideasFor(r));
    }),

    // CS-1 to CS-4: ideas pooled across resumes (same text = same idea), newest resume first.
    // CS-11: no job gaps in the mock; tests add them with server.use.
    http.get(`${API}/stories/recommendations`, () => {
      const ideas = new Map<string, StoryRecommendations["ideas"][number]>();
      const resumes = store.db.resumes
        .filter((r) => !r.deleted && r.resume)
        .sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
      for (const r of resumes) {
        for (const idea of ideasFor(r).ideas) {
          const key = normalize(idea.achievement);
          const seen = ideas.get(key);
          if (seen) seen.resumes += 1;
          else ideas.set(key, { kind: "resume_idea", ...idea, resume_id: r.id, resumes: 1 });
        }
      }
      const body: StoryRecommendations = { skills: [], ideas: [...ideas.values()] };
      return HttpResponse.json(body);
    }),

    // RSD-16: every read resume's counts in one request, with the rules above.
    http.get(`${API}/story-ideas/counts`, () => {
      const out: StoryIdeaCount[] = store.db.resumes.filter((r) => !r.deleted && r.resume)
        .map((r) => {
          const found = ideasFor(r);
          return { resume_id: r.id, ideas: found.ideas.length, used: found.used.length };
        });
      return HttpResponse.json(out);
    }),

    http.post(`${API}/resumes/:resumeId/story-ideas/dismiss`, async ({ params, request }) => {
      const r = live(params.resumeId);
      if (!r) return notFound();
      if (!r.resume) return reading();
      const { resume_line_ref: ref } = (await request.json()) as { resume_line_ref?: string };
      const m = /^roles\[(\d+)\]\.achievements\[(\d+)\]$/.exec(ref ?? "");
      if (!m) return HttpResponse.json({ detail: [{ msg: "resume_line_ref is not valid" }] }, { status: 422 });
      const text = r.resume.roles[Number(m[1])]?.achievements[Number(m[2])];
      if (!text?.trim()) return HttpResponse.json({ detail: "No achievement at that place" }, { status: 404 });
      const list = (dismissed()[r.id] ??= []);
      if (!list.includes(normalize(text))) list.push(normalize(text));
      store.save();
      return new HttpResponse(null, { status: 204 });
    }),

    http.patch(`${API}/account/profile`, async ({ request }) => {
      const email = store.db.auth.userEmail;
      if (!email) return HttpResponse.json({ detail: "Sign in first" }, { status: 401 });
      const body = (await request.json()) as PlanSettingsIn & Record<string, unknown>;
      const extra = Object.keys(body).filter((k) => k !== "plan_style" && k !== "plan_email_muted");
      const style = body.plan_style;
      if (extra.length > 0 || (style != null && style !== "weekly" && style !== "checklist")) {
        return HttpResponse.json({ detail: [{ msg: "Only plan_style and plan_email_muted" }] }, { status: 422 });
      }
      const profile = (store.db.profiles[email] ??= { ...EMPTY_PROFILE });
      if (style) profile.plan_style = style;
      if (typeof body.plan_email_muted === "boolean") profile.plan_email_muted = body.plan_email_muted;
      store.save();
      return HttpResponse.json(profile);
    }),
  ];
}
