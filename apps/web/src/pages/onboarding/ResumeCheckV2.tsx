/**
 * v2 "Check your resume" (IN-3, IN-12, RMAP-9): one guided page with four steps (D-6): your career
 * journey, Strova's findings, stories to tell in interviews and stronger resume lines. The header
 * has the name, the default chip, the dates, the roles that use it and the actions (RSD-7). This
 * component owns the draft, the editors, the checks and save; the steps get props and callbacks.
 * Saving sends the full Resume contract to PUT /resumes/{id}. The checks are rule-based and run on
 * every edit (resumeChecks.ts, D-7).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { keys, useJob, useStoryIdeas } from "../../api/hooks";
import { resumesApi } from "../../api/inputs";
import { rolesApi } from "../../api/roles";
import { useSuggestions } from "../../api/suggestions";
import type { Resume } from "../../api/types";
import { ErrorNotice, Steps } from "../../components/ui";
import { contextPath, newJobPath } from "../../paths";
import { usingRoleCount } from "../resumes/ResumesListPage";
import { addRolePath, dateChip, rolePath, roleTitle } from "../roles/shared";
import { START } from "../start/paths";
import { useAcceptedIssues } from "./acceptedIssues";
import { CareerStrip } from "./check/CareerStrip";
import {
  cvDraftToResume,
  forChecks,
  newKey,
  omit,
  toCvDraft,
  validateRole,
  without,
  type CvDraft,
  type CvRole,
  type RoleErrors,
} from "./check/draft";
import { Drawer } from "./check/Drawer";
import { AcceptedList, FindingsStep, orderFindings, WhatStrovaChecks } from "./check/FindingsStep";
import { LinesStep } from "./check/LinesStep";
import { StoriesStep } from "./check/StoriesStep";
import { JourneyStep } from "./check/JourneyStep";
import { CHECK_STEPS, defaultStep, ONBOARDING_STEPS, parseStep, StepList, type CheckStep, type StepInfo } from "./check/StepList";
import { checkResume, thisMonth, type ResumeIssue } from "./resumeChecks";
import { shortDate } from "./resumeSummary";
import { onboardingLinks, STEP_NOTES, useOnboardingSteps } from "./steps";

export { cvDraftToResume, toCvDraft, validateRole, type CvDraft, type CvRole } from "./check/draft";

/** The field to focus and highlight after Fix, by element id. */
interface Flash {
  id: string;
  n: number;
}

const monthIndex = (value: string): number | null => {
  const m = /^(\d{4})(?:-(\d{2}))?$/.exec(value.trim());
  return m ? Number(m[1]) * 12 + (m[2] ? Number(m[2]) - 1 : 0) : null;
};

/** RSD-8: "4 roles · 9 years · 11 achievements". */
export function journeyLine(roles: CvRole[], today: string): string {
  const now = monthIndex(today) ?? 0;
  const starts = roles.map((r) => monthIndex(r.start)).filter((n): n is number => n !== null);
  const ends = roles.map((r) => (r.end.trim() ? monthIndex(r.end) : now)).filter((n): n is number => n !== null);
  const years = starts.length && ends.length ? Math.max(0, Math.round((Math.max(...ends) - Math.min(...starts)) / 12)) : null;
  const achievements = roles.reduce((n, r) => n + r.achievements.filter((a) => a.trim()).length, 0);
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  return [
    plural(roles.length, "role", "roles"),
    years === null ? null : plural(years, "year", "years"),
    plural(achievements, "achievement", "achievements"),
  ]
    .filter(Boolean)
    .join(" · ");
}

export function ResumeCheckV2({
  jobId,
  resumeId,
  name,
  original,
  accepted: acceptedInitial = [],
  fresh = false,
  confirmedAt = null,
  uploadedAt = null,
  isMain = false,
}: {
  jobId: string;
  resumeId: string;
  name: string | null;
  original: Resume;
  /** Issues the user accepted before (IN-12). */
  accepted?: readonly { key: string }[];
  /**
   * The resume was just read and not confirmed yet: say where the user is. Otherwise the user came
   * back to a saved resume (from Resumes, Home, the plan or a link), and the next step says so.
   */
  fresh?: boolean;
  /** When the resume was last saved from this page (ResumeOut.confirmed_at). */
  confirmedAt?: string | null;
  uploadedAt?: string | null;
  /** RSD-7, RM-2: the default resume shows the Default chip; another one offers Set as default. */
  isMain?: boolean;
}) {
  const steps = useOnboardingSteps();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const onboarding = Boolean(jobId);
  const job = useJob(jobId, false);
  const posting = jobId ? (job.data?.posting ?? null) : null;
  const [today] = useState(thisMonth);
  const accepted = useAcceptedIssues(resumeId, acceptedInitial);
  // D-4: the same rule as the Resumes list; the roles drawer comes in RS05.
  const roles = useQuery({ queryKey: ["roles"], queryFn: rolesApi.list, enabled: !onboarding });
  const ideas = useStoryIdeas(onboarding ? null : resumeId);
  const rewrites = useSuggestions("resume", { resume_id: resumeId });

  const [draft, setDraft] = useState<CvDraft>(() => toCvDraft(original));
  /** Roles open for editing, by role key: the edited copy. */
  const [editing, setEditing] = useState<Record<number, CvRole>>({});
  const [roleErrors, setRoleErrors] = useState<Record<number, RoleErrors>>({});
  const [openSection, setOpenSection] = useState<Record<string, boolean>>({});
  const [shown, setShown] = useState<Set<number>>(() => new Set());
  const [flash, setFlash] = useState<Flash | null>(null);
  /** Roles added on this page and not saved yet: Cancel removes them again. */
  const [added, setAdded] = useState<ReadonlySet<number>>(() => new Set());
  const [saved, setSaved] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [madeMain, setMadeMain] = useState(false);
  /** The finding shown on step 2, by key; the first one when unset or gone. */
  const [findingKey, setFindingKey] = useState<string | null>(null);
  /** RSD-14: the open drawer, if any. */
  const [drawer, setDrawer] = useState<"roles" | "accepted" | "checks" | null>(null);

  // The checks read what the user sees, open editors included.
  const live = useMemo(
    () => ({ ...draft, roles: draft.roles.map((r) => editing[r.key] ?? r) }),
    [draft, editing],
  );
  const issues = useMemo(() => checkResume(forChecks(live), { today, job: posting }), [live, today, posting]);
  const open = issues.filter((i) => !accepted.keys.has(i.key));
  // Step 2 walks the findings of the saved draft, so a finding stays in view while its fix is typed.
  const settledIssues = useMemo(() => checkResume(forChecks(draft), { today, job: posting }), [draft, today, posting]);
  const findings = useMemo(
    () => orderFindings(settledIssues.filter((i) => !accepted.keys.has(i.key))),
    [settledIssues, accepted.keys],
  );
  const acceptedFindings = issues.filter((i) => accepted.keys.has(i.key));
  const [lastIndex, setLastIndex] = useState(0);
  const keyIndex = findingKey ? findings.findIndex((f) => f.key === findingKey) : -1;
  // A fixed or accepted finding leaves the list: the next one takes its place (RSD-10).
  const findingIndex = keyIndex >= 0 ? keyIndex : Math.min(lastIndex, Math.max(0, findings.length - 1));
  const currentFinding = findings[findingIndex];
  const selectFinding = (index: number) => {
    const f = findings[index];
    if (!f) return;
    setFindingKey(f.key);
    setLastIndex(index);
  };

  const step: CheckStep = parseStep(params.get("step"), onboarding) ?? defaultStep(open.length, onboarding);
  const goStep = (next: CheckStep) =>
    setParams(
      (p) => {
        const q = new URLSearchParams(p);
        q.set("step", next);
        return q;
      },
      { replace: false },
    );

  useEffect(() => {
    if (!flash) return;
    const el = document.getElementById(flash.id);
    if (el) {
      el.scrollIntoView?.({ block: "center", behavior: "smooth" });
      el.focus();
    }
    const timer = window.setTimeout(() => setFlash(null), 2400);
    return () => window.clearTimeout(timer);
  }, [flash]);

  const focus = (id: string) => setFlash((f) => ({ id, n: (f?.n ?? 0) + 1 }));

  const save = useMutation({
    mutationFn: (resume: Resume) => resumesApi.update(resumeId, resume),
    onSuccess: (record) => {
      queryClient.setQueryData(keys.resume(resumeId), record);
      void queryClient.invalidateQueries({ queryKey: keys.resumes, exact: true });
    },
  });

  const editRole = (role: CvRole) => {
    setEditing((e) => (e[role.key] ? e : { ...e, [role.key]: { ...role, achievements: [...role.achievements] } }));
    setShown((s) => new Set(s).add(role.key));
  };
  const closeRole = (key: number) => {
    setEditing((e) => omit(e, key));
    setRoleErrors((e) => omit(e, key));
    setAdded((a) => without(a, key));
  };
  /** Cancel: a role added here and never saved goes away, so Cancel never leaves an empty role behind. */
  const cancelRole = (key: number) => {
    if (added.has(key)) setDraft((d) => ({ ...d, roles: d.roles.filter((r) => r.key !== key) }));
    closeRole(key);
  };
  const changeRole = (key: number, change: Partial<CvRole>) =>
    setEditing((e) => ({ ...e, [key]: { ...e[key], ...change } }));
  const saveRole = (key: number) => {
    const copy = editing[key];
    const errors = validateRole(copy);
    if (Object.keys(errors).length > 0) {
      setRoleErrors((r) => ({ ...r, [key]: errors }));
      focus(`role-${key}-${Object.keys(errors)[0]}`);
      return;
    }
    setDraft((d) => ({ ...d, roles: d.roles.map((r) => (r.key === key ? copy : r)) }));
    closeRole(key);
  };
  const addRole = () => {
    const role: CvRole = { key: newKey(), company: "", title: "", start: "", end: "", achievements: [""], skills: [] };
    setDraft((d) => ({ ...d, roles: [...d.roles, role] }));
    setEditing((e) => ({ ...e, [role.key]: role }));
    setAdded((a) => new Set(a).add(role.key));
    focus(`role-${role.key}-title`);
  };
  const removeRole = (key: number) => {
    setDraft((d) => ({ ...d, roles: d.roles.filter((r) => r.key !== key) }));
    closeRole(key);
  };
  const moveRole = (key: number, by: -1 | 1) => {
    setDraft((d) => {
      const i = d.roles.findIndex((r) => r.key === key);
      const j = i + by;
      if (i < 0 || j < 0 || j >= d.roles.length) return d;
      const roles = [...d.roles];
      [roles[i], roles[j]] = [roles[j], roles[i]];
      return { ...d, roles };
    });
    focus(`role-${key}-move-${by < 0 ? "up" : "down"}`);
  };
  /**
   * Moves an achievement from an open role to the end of another role. The other role opens for
   * editing too, so both changes are saved or cancelled together and nothing is copied twice.
   */
  const moveAchievement = (fromKey: number, item: number, toKey: number) => {
    const text = editing[fromKey].achievements[item];
    const target = editing[toKey] ?? draft.roles.find((r) => r.key === toKey);
    if (!target) return;
    setEditing((e) => ({
      ...e,
      [fromKey]: { ...e[fromKey], achievements: e[fromKey].achievements.filter((_, j) => j !== item) },
      [toKey]: { ...target, achievements: [...target.achievements, text] },
    }));
    setShown((s) => new Set(s).add(toKey));
  };

  /** RSD-9: a finding chip or a gap link opens the first of those findings on step 2. */
  const showFindings = (list: ResumeIssue[]) => {
    const first = orderFindings(list)[0];
    if (!first) return;
    const index = findings.findIndex((f) => f.key === first.key);
    if (index >= 0) selectFinding(index);
    else setFindingKey(first.key);
    goStep("findings");
  };

  /** A finding with no fix in place: open its field on step 1, as Fix did before (IN-12). */
  const fix = (issue: ResumeIssue) => {
    goStep("journey");
    const t = issue.target;
    if (t.section === "summary" || t.section === "skills") {
      setOpenSection((s) => ({ ...s, [t.section]: true }));
      focus(`cv-${t.section}`);
      return;
    }
    const role = draft.roles[t.role];
    if (!role) return;
    const copy = editing[role.key] ?? role;
    editRole(role);
    if (t.field === "achievements") {
      const empty = copy.achievements.findIndex((a) => !a.trim());
      const item = empty >= 0 ? empty : copy.achievements.length;
      if (empty < 0) {
        setEditing((e) => {
          const base = e[role.key] ?? copy;
          return { ...e, [role.key]: { ...base, achievements: [...base.achievements, ""] } };
        });
      }
      focus(`role-${role.key}-achievement-${item}`);
    } else if (t.field === "achievement") {
      focus(`role-${role.key}-achievement-${t.item ?? 0}`);
    } else {
      focus(`role-${role.key}-${t.field}`);
    }
  };

  /** Validates every role, open editors included. Returns the Resume, or null and opens the bad roles. */
  const build = (): { resume: Resume; roles: CvRole[] } | null => {
    const roles = live.roles;
    const errors: Record<number, RoleErrors> = {};
    for (const r of roles) {
      const e = validateRole(r);
      if (Object.keys(e).length > 0) errors[r.key] = e;
    }
    const bad = Object.keys(errors).map(Number);
    if (bad.length > 0) {
      setEditing((e) => {
        const next = { ...e };
        for (const r of roles) if (errors[r.key] && !next[r.key]) next[r.key] = r;
        return next;
      });
      setRoleErrors(errors);
      setBlocked(true);
      focus(`role-${bad[0]}-${Object.keys(errors[bad[0]])[0]}`);
      return null;
    }
    setBlocked(false);
    return { resume: cvDraftToResume(live), roles };
  };

  const commit = (roles: CvRole[]) => {
    setDraft((d) => ({ ...d, roles }));
    setEditing({});
    setRoleErrors({});
    setAdded(new Set());
  };

  const onSaveDraft = () => {
    const built = build();
    if (!built) return;
    setSaved(false);
    save.mutate(built.resume, {
      onSuccess: () => {
        commit(built.roles);
        setSaved(true);
      },
    });
  };

  /** Saves the CV, then goes to `path`. */
  const saveThen = (path: string) => {
    const built = build();
    if (!built) return;
    save.mutate(built.resume, { onSuccess: () => navigate(path) });
  };

  /** RSD-10: the fix in place edits the role's open copy, like the editor on step 1. */
  const fixRoleField = (index: number, field: "start" | "end" | "title", value: string) => {
    const role = draft.roles[index];
    if (!role) return;
    setEditing((e) => {
      const base = e[role.key] ?? { ...role, achievements: [...role.achievements] };
      return { ...e, [role.key]: { ...base, [field]: value } };
    });
  };
  const fixAchievement = (index: number, item: number, text: string) => {
    const role = draft.roles[index];
    if (!role) return;
    setEditing((e) => {
      const base = e[role.key] ?? { ...role, achievements: [...role.achievements] };
      const achievements = [...base.achievements];
      while (achievements.length <= item) achievements.push("");
      achievements[item] = text;
      return { ...e, [role.key]: { ...base, achievements } };
    });
  };
  /** Saves the open fixes (and any open editor), then the next finding shows. */
  const saveFix = () => {
    const built = build();
    if (!built) return;
    setSaved(false);
    save.mutate(built.resume, {
      onSuccess: () => {
        commit(built.roles);
        setSaved(true);
      },
    });
  };
  const addSkills = (skills: string[]) => {
    const next = { ...live, skills: [...new Set([...live.skills, ...skills])] };
    setDraft((d) => ({ ...d, skills: next.skills }));
    const errors = next.roles.some((r) => Object.keys(validateRole(r)).length > 0);
    if (!errors) save.mutate(cvDraftToResume(next), { onSuccess: () => setSaved(true) });
  };

  const makeMain = useMutation({
    mutationFn: () => resumesApi.setMain(resumeId),
    onSuccess: () => {
      setMadeMain(true);
      void queryClient.invalidateQueries({ queryKey: keys.resumes });
      void queryClient.invalidateQueries({ queryKey: keys.resume(resumeId) });
    },
  });

  const primaryLabel = jobId
    ? "Continue to your interview plan"
    : fresh
      ? "Add a job description to practice for"
      : "Use this resume for an interview";
  const primary = (
    <button
      type="button"
      className="btn"
      onClick={() => saveThen(jobId ? contextPath(jobId, resumeId) : newJobPath("rehearsal"))}
      disabled={save.isPending}
    >
      {primaryLabel}
    </button>
  );
  // The save actions under the journey and in onboarding: Save draft, or save and go back.
  const saveButton = jobId ? (
    <button type="button" className="btn btn--secondary" onClick={onSaveDraft} disabled={save.isPending}>
      Save draft
    </button>
  ) : (
    <button type="button" className="btn btn--secondary" onClick={() => saveThen("/resumes")} disabled={save.isPending}>
      Save and go back to resumes
    </button>
  );

  const usedBy = onboarding ? 0 : (usingRoleCount(roles.data, resumeId) ?? 0);
  const high = findings.filter((f) => f.severity === "high").length;
  const ideaCount = ideas.data ? ideas.data.ideas.length : null;
  const lineCount = rewrites.data ? rewrites.data.filter((s) => s.kind === "improve_resume_line").length : null;
  const info: Record<CheckStep, StepInfo> = {
    journey: { count: null, line: journeyLine(live.roles, today) },
    findings: { count: findings.length, line: `and the fixes she recommends · ${high} high` },
    stories: { count: ideaCount, line: null },
    lines: { count: lineCount, line: null },
  };
  const visibleSteps = onboarding ? ONBOARDING_STEPS : CHECK_STEPS;
  const isDefault = isMain || madeMain;
  const dates = [
    uploadedAt ? `Added ${shortDate(uploadedAt)}` : null,
    confirmedAt ? `Last saved ${shortDate(confirmedAt)}` : "Not saved yet",
  ]
    .filter(Boolean)
    .join(" · ");

  const footerLinks = (
    <>
      {usedBy > 0 && (
        <button type="button" className="cvc-link" aria-haspopup="dialog" onClick={() => setDrawer("roles")}>
          {usedBy} {usedBy === 1 ? "role uses" : "roles use"} this resume ›
        </button>
      )}
      <button type="button" className="cvc-link" aria-haspopup="dialog" onClick={() => setDrawer("accepted")}>
        Findings you accepted · {acceptedFindings.length} ›
      </button>
      <button type="button" className="cvc-link" aria-haspopup="dialog" onClick={() => setDrawer("checks")}>
        What Strova checks ›
      </button>
    </>
  );
  // RSD-14: the active roles whose interviews use this resume (the rule behind the count, D-4).
  const usingRoles = (roles.data ?? []).filter(
    (r) => !r.role.archived && r.interviews.some((i) => i.interview.resume_id === resumeId),
  );
  /** RSD-12: after a rewrite is added or undone, step 1 shows the saved resume again. */
  const reloadSaved = async () => {
    const record = await resumesApi.get(resumeId);
    queryClient.setQueryData(keys.resume(resumeId), record);
    if (record.resume) {
      setDraft(toCvDraft(record.resume));
      setEditing({});
      setRoleErrors({});
      setAdded(new Set());
    }
  };

  const nextCard = (
    <section className="cvc-card cvc-next" aria-label="Next step">
      <p>
        <b>Looks right?</b>{" "}
        {jobId
          ? "Next, your interview plan for this job."
          : fresh
            ? "Next, add a job description and we compare your resume with it."
            : "Use it for an interview: add the job description and we compare your resume with it."}
      </p>
      <div className="row cvc-actions">
        {saveButton}
        {primary}
      </div>
    </section>
  );

  return (
    <div className="cvc cvc--steps">
      {jobId && <Steps current={1} steps={steps} links={onboardingLinks(jobId)} note={STEP_NOTES.check} />}
      {fresh && (
        <p className="cvc-landing" role="status">
          We read your resume. Check it, then continue.
        </p>
      )}
      {!onboarding && (
        <button type="button" className="cvc-link cvc-back" onClick={() => saveThen("/resumes")} disabled={save.isPending}>
          <span aria-hidden="true">← </span>Back to resumes
        </button>
      )}
      <header className="cvc-top">
        <div className="cvc-top__main">
          <div className="cvc-top__title">
            <h1>{onboarding ? "Check your resume" : (name ?? "Your resume")}</h1>
            {!onboarding &&
              (isDefault ? (
                <span className="sx-chip dark">Default</span>
              ) : (
                <button type="button" className="sx-btn ghost sm" onClick={() => makeMain.mutate()} disabled={makeMain.isPending}>
                  Set as default
                </button>
              ))}
          </div>
          <p className="cvc-top__meta muted small">
            <span className="cvc-saved" data-testid="cvc-saved">
              {dates}
            </span>
            {usedBy > 0 && (
              <>
                {" · "}
                <button
                  type="button"
                  className="cvc-link cvc-link--inline"
                  data-testid="used-by"
                  aria-haspopup="dialog"
                  onClick={() => setDrawer("roles")}
                >
                  Used by {usedBy} {usedBy === 1 ? "role" : "roles"}
                </button>
              </>
            )}
          </p>
          {onboarding && (
            <p className="cvc-top__intro">
              We read your resume into the parts below. Fix anything we got wrong, and look at what Strova found. Interviewers and
              your match scores read this version.
            </p>
          )}
        </div>
        <div className="row cvc-top__actions">
          {onboarding ? (
            saveButton
          ) : (
            <Link className="btn btn--secondary" to={START}>
              Upload a new version
            </Link>
          )}
          {primary}
        </div>
      </header>
      <div aria-live="polite" className="cvc-status">
        {saved && !save.isPending && <p className="muted">Draft saved.</p>}
      </div>
      {blocked && (
        <p className="field-error" role="alert">
          Fix the fields marked in red, then continue.
        </p>
      )}
      {save.isError && <ErrorNotice error={save.error} />}
      {makeMain.isError && <ErrorNotice error={makeMain.error} />}

      <div className="cvc-guided">
        <StepList steps={visibleSteps} current={step} info={info} onSelect={goStep} footer={footerLinks} />
        <div className="cvc-view">
          {step === "journey" && (
            <JourneyStep
              draft={draft}
              editing={editing}
              roleErrors={roleErrors}
              openSection={openSection}
              setOpenSection={(section, value) => setOpenSection((s) => ({ ...s, [section]: value }))}
              shown={shown}
              today={today}
              flash={flash?.id}
              open={open}
              onSaveSummary={(summary) => setDraft((d) => ({ ...d, summary }))}
              onSaveSkills={(skills) => setDraft((d) => ({ ...d, skills }))}
              onSaveEducation={(education) => setDraft((d) => ({ ...d, education }))}
              onSaveCertifications={(certifications) => setDraft((d) => ({ ...d, certifications }))}
              onShowRole={(key) => setShown((s) => new Set(s).add(key))}
              onEditRole={(role) => {
                editRole(role);
                focus(`role-${role.key}-title`);
              }}
              onChangeRole={changeRole}
              onCancelRole={cancelRole}
              onSaveRole={saveRole}
              onRemoveRole={removeRole}
              onMoveRole={moveRole}
              onMoveAchievement={moveAchievement}
              onAddRole={addRole}
              onShowFindings={showFindings}
              footer={nextCard}
            />
          )}
          {step === "findings" && (
            <FindingsStep
              findings={findings}
              current={findingIndex}
              onSelect={selectFinding}
              roles={live.roles}
              savedRoles={draft.roles}
              summary={live.summary}
              jobId={jobId}
              accepted={accepted}
              saving={save.isPending}
              errorFor={(role, field) => roleErrors[role.key]?.[field]}
              onRoleField={fixRoleField}
              onAchievement={fixAchievement}
              onSummary={(summary) => setDraft((d) => ({ ...d, summary }))}
              onSave={saveFix}
              onAddSkills={addSkills}
              onFixElsewhere={fix}
              onOpenJourney={() => goStep("journey")}
            />
          )}
          {step === "stories" && <StoriesStep resumeId={resumeId} />}
          {step === "lines" && <LinesStep resumeId={resumeId} onResumeChanged={() => void reloadSaved()} />}
          {step !== "journey" && (
            <CareerStrip
              roles={live.roles}
              today={today}
              outlined={step === "findings" && currentFinding ? currentFinding.roles : []}
              onOpen={() => goStep("journey")}
            />
          )}
          {step === "findings" && onboarding && nextCard}
        </div>
      </div>

      <Drawer
        open={drawer === "roles"}
        title={`Used by ${usingRoles.length} ${usingRoles.length === 1 ? "role" : "roles"}`}
        onClose={() => setDrawer(null)}
      >
        <p className="muted small">These roles rehearse with this resume. Edits here change what their interviewers read.</p>
        <ul className="cvc-drawer__rows" aria-label="Roles that use this resume">
          {usingRoles.map(({ role }) => (
            <li key={role.id} className="cvc-drawer__row">
              <span className="cvc-drawer__who">
                <b>{role.company_name ?? roleTitle(role)}</b>
                {role.company_name && <span className="muted small">{role.title ?? role.name}</span>}
              </span>
              <span className="row">
                <span className="sx-chip">{dateChip(role).text}</span>
                <Link to={rolePath(role.id)} aria-label={`Open ${roleTitle(role)}`}>
                  Open
                </Link>
              </span>
            </li>
          ))}
        </ul>
        <Link className="btn btn--secondary btn--small" to={addRolePath}>
          Add a target role with this resume
        </Link>
      </Drawer>
      <Drawer
        open={drawer === "accepted"}
        title={`Findings you accepted · ${acceptedFindings.length}`}
        onClose={() => setDrawer(null)}
      >
        <AcceptedList findings={acceptedFindings} accepted={accepted} />
      </Drawer>
      <Drawer open={drawer === "checks"} title="What Strova checks" onClose={() => setDrawer(null)}>
        <WhatStrovaChecks />
      </Drawer>
    </div>
  );
}
