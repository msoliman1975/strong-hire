/**
 * v2 "Check your CV" (IN-3, IN-12), built as drawn on the App UX canvas (ResumeCheck board): the
 * CV as cards on the left, "What we found" on the right. Saving sends the full Resume contract to
 * PUT /resumes/{id}. The checks are rule-based and run on every edit (resumeChecks.ts).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";

import { keys, useJob } from "../../api/hooks";
import { resumesApi } from "../../api/inputs";
import type { Resume } from "../../api/types";
import { ErrorNotice, PageHead, Steps } from "../../components/ui";
import { contextPath, newJobPath } from "../../paths";
import { useAcceptedIssues, type AcceptedIssues } from "./acceptedIssues";
import {
  checkResume,
  formatDate,
  formatSpan,
  groupSkills,
  GROUP_SKILLS_OVER,
  newestFirst,
  thisMonth,
  type IssueGroup,
  type ResumeIssue,
} from "./resumeChecks";
import { issuesOpen, shortDate } from "./resumeSummary";
import { onboardingLinks, STEP_NOTES, useOnboardingSteps } from "./steps";

type Education = Resume["education"][number];

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

type RoleErrors = Partial<Record<"company" | "title" | "start" | "end", string>>;

const DATE = /^\d{4}(-(0[1-9]|1[0-2]))?$/;
/** Roles after this many show as one line until opened. */
const OPEN_ROLES = 2;

let nextKey = 1;
const newKey = () => nextKey++;

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

const cleanList = (items: string[]) => [...new Set(items.map((s) => s.trim()).filter(Boolean))];

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
function forChecks(draft: CvDraft): Resume {
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
function omit<T>(record: Record<number, T>, key: number): Record<number, T> {
  const next = { ...record };
  delete next[key];
  return next;
}

/** A copy of `set` without `key`. */
function without<T>(set: ReadonlySet<T>, key: T): ReadonlySet<T> {
  if (!set.has(key)) return set;
  const next = new Set(set);
  next.delete(key);
  return next;
}

const splitList =(text: string, by: RegExp) => text.split(by).map((s) => s.trim()).filter(Boolean);

type Filter = "all" | "dates" | "detail" | "accepted";
const GROUP_LABEL: Record<IssueGroup, string> = {
  dates: "Dates",
  detail: "Detail",
  level: "Level",
  consistency: "Consistency",
  job: "Job",
};

/** The field to focus and highlight after Fix, by element id. */
interface Flash {
  id: string;
  n: number;
}

/** Issues to scroll to and highlight in the panel, by key. `n` repeats it on every click. */
interface Highlight {
  keys: string[];
  n: number;
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
}: {
  jobId: string;
  resumeId: string;
  name: string | null;
  original: Resume;
  /** Issues the user accepted before (IN-12). */
  accepted?: readonly { key: string }[];
  /**
   * The CV was just read and not confirmed yet: say where the user is. Otherwise the user came back
   * to a saved CV (from Resumes, Home, the plan or a link), and the next step says so.
   */
  fresh?: boolean;
  /** When the CV was last saved from this page (ResumeOut.confirmed_at). */
  confirmedAt?: string | null;
  uploadedAt?: string | null;
}) {
  const steps = useOnboardingSteps();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const job = useJob(jobId, false);
  const posting = jobId ? (job.data?.posting ?? null) : null;
  const [today] = useState(thisMonth);
  const accepted = useAcceptedIssues(resumeId, acceptedInitial);

  const [draft, setDraft] = useState<CvDraft>(() => toCvDraft(original));
  /** Roles open for editing, by role key: the edited copy. */
  const [editing, setEditing] = useState<Record<number, CvRole>>({});
  const [roleErrors, setRoleErrors] = useState<Record<number, RoleErrors>>({});
  const [openSection, setOpenSection] = useState<Record<string, boolean>>({});
  const [shown, setShown] = useState<Set<number>>(() => new Set());
  const [flash, setFlash] = useState<Flash | null>(null);
  /** Roles added on this page and not saved yet: Cancel removes them again. */
  const [added, setAdded] = useState<ReadonlySet<number>>(() => new Set());
  /** Issues to point at in the panel after a click on an issue count. */
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const [saved, setSaved] = useState(false);
  const [blocked, setBlocked] = useState(false);

  // The checks read what the user sees, open editors included.
  const live = useMemo(
    () => ({ ...draft, roles: draft.roles.map((r) => editing[r.key] ?? r) }),
    [draft, editing],
  );
  const issues = useMemo(() => checkResume(forChecks(live), { today, job: posting }), [live, today, posting]);
  const open = issues.filter((i) => !accepted.keys.has(i.key));

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

  // The highlight in the panel fades like the field flash.
  const highlights = useRef(0);
  useEffect(() => {
    if (!highlight) return;
    const timer = window.setTimeout(() => setHighlight(null), 2400);
    return () => window.clearTimeout(timer);
  }, [highlight]);

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

  /** A click on an issue count: show those issues in the panel. */
  const showIssues = (list: ResumeIssue[]) => {
    if (list.length === 0) return;
    highlights.current += 1;
    setHighlight({ keys: list.map((i) => i.key), n: highlights.current });
  };

  const fix = (issue: ResumeIssue) => {
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

  // One obvious next step: the interview plan inside a rehearsal. From Resumes, a job to practice
  // for right after an upload, or this CV for an interview when the user comes back to it.
  const actions = (
    <div className="row cvc-actions">
      {jobId ? (
        <button type="button" className="btn btn--secondary" onClick={onSaveDraft} disabled={save.isPending}>
          Save draft
        </button>
      ) : (
        <button type="button" className="btn btn--secondary" onClick={() => saveThen("/resumes")} disabled={save.isPending}>
          Back to resumes
        </button>
      )}
      <button
        type="button"
        className="btn"
        onClick={() => saveThen(jobId ? contextPath(jobId, resumeId) : newJobPath("rehearsal"))}
        disabled={save.isPending}
      >
        {jobId
          ? "Continue to your interview plan"
          : fresh
            ? "Add a job description to practice for"
            : "Use this CV for an interview"}
      </button>
    </div>
  );

  const issuesFor = (index: number) => open.filter((i) => i.roles.includes(index));

  return (
    <div className="cvc">
      {jobId && <Steps current={1} steps={steps} links={onboardingLinks(jobId)} note={STEP_NOTES.check} />}
      {fresh && (
        <p className="cvc-landing" role="status">
          We read your CV. Check it, then continue.
        </p>
      )}
      <div className="cvc-head">
        <PageHead title="Check your CV" eyebrow={name ? `Resumes · ${name}` : "Resumes"} eyebrowTone="muted">
          <p>
            We read your CV into the parts below. Fix anything we got wrong, and look at what we found. Interviewers and
            your match scores read this version.
          </p>
          <p className="muted small cvc-saved" data-testid="cvc-saved">
            {confirmedAt
              ? `Last saved ${shortDate(confirmedAt)}`
              : `${uploadedAt ? `Added ${shortDate(uploadedAt)} · ` : ""}Not saved yet`}{" "}
            · {issuesOpen(open.length)}
          </p>
        </PageHead>
        <div className="cvc-head__actions">{actions}</div>
      </div>
      <div aria-live="polite" className="cvc-status">
        {saved && !save.isPending && <p className="muted">Draft saved.</p>}
      </div>
      {blocked && (
        <p className="field-error" role="alert">
          Fix the fields marked in red, then continue.
        </p>
      )}
      {save.isError && <ErrorNotice error={save.error} />}

      <div className="cvc-grid">
        <div className="cvc-cv">
          <SummaryCard
            summary={draft.summary}
            open={Boolean(openSection.summary)}
            setOpen={(v) => setOpenSection((s) => ({ ...s, summary: v }))}
            onSave={(summary) => setDraft((d) => ({ ...d, summary }))}
            notes={open.filter((i) => i.target.section === "summary")}
            flash={flash?.id}
            onShowIssues={showIssues}
          />

          <p className="cvc-label cvc-label--section">
            Experience · {draft.roles.length} {draft.roles.length === 1 ? "role" : "roles"}
            {draft.roles.length > 1 ? " · newest first" : ""}
          </p>
          {draft.roles.length === 0 && <p className="muted">We found no roles in your CV. Add one if you want.</p>}
          {draft.roles.map((role, index) => {
            const copy = editing[role.key];
            const roleIssues = issuesFor(index);
            if (copy) {
              return (
                <RoleEditor
                  key={role.key}
                  role={copy}
                  index={index}
                  count={draft.roles.length}
                  issues={roleIssues.filter((i) => i.target.section === "role" && i.target.role === index)}
                  allIssues={roleIssues}
                  errors={roleErrors[role.key] ?? {}}
                  others={draft.roles.filter((r) => r.key !== role.key).map((r) => editing[r.key] ?? r)}
                  flash={flash?.id}
                  onChange={(change) => changeRole(role.key, change)}
                  onShowIssues={() => showIssues(roleIssues)}
                  onCancel={() => cancelRole(role.key)}
                  onSave={() => saveRole(role.key)}
                  onRemove={() => removeRole(role.key)}
                  onMove={(by) => moveRole(role.key, by)}
                  onMoveAchievement={(item, to) => moveAchievement(role.key, item, to)}
                />
              );
            }
            const collapsed = index >= OPEN_ROLES && !shown.has(role.key);
            return (
              <RoleCard
                key={role.key}
                role={role}
                today={today}
                collapsed={collapsed}
                current={index === 0}
                issueCount={roleIssues.length}
                onShowIssues={() => showIssues(roleIssues)}
                onShow={() => setShown((s) => new Set(s).add(role.key))}
                onEdit={() => {
                  editRole(role);
                  focus(`role-${role.key}-title`);
                }}
              />
            );
          })}

          <button type="button" className="cvc-link cvc-add" onClick={addRole}>
            + Add a role
          </button>

          <div className="cvc-pair">
            <SkillsCard
              skills={draft.skills}
              open={Boolean(openSection.skills)}
              setOpen={(v) => setOpenSection((s) => ({ ...s, skills: v }))}
              onSave={(skills) => setDraft((d) => ({ ...d, skills }))}
              flash={flash?.id}
              issues={open.filter((i) => i.target.section === "skills")}
              onShowIssues={showIssues}
            />
            <EducationCard
              education={draft.education}
              open={Boolean(openSection.education)}
              setOpen={(v) => setOpenSection((s) => ({ ...s, education: v }))}
              onSave={(education) => setDraft((d) => ({ ...d, education }))}
            />
            <CertificationsCard
              certifications={draft.certifications}
              open={Boolean(openSection.certifications)}
              setOpen={(v) => setOpenSection((s) => ({ ...s, certifications: v }))}
              onSave={(certifications) => setDraft((d) => ({ ...d, certifications }))}
            />
          </div>

          <section className="cvc-card cvc-next" aria-label="Next step">
            <p>
              <b>Looks right?</b>{" "}
              {jobId
                ? "Next, your interview plan for this job."
                : fresh
                  ? "Next, add a job description and we compare your CV with it."
                  : "Use it for an interview: add the job description and we compare your CV with it."}
            </p>
            {actions}
          </section>
        </div>

        <IssuesPanel issues={issues} accepted={accepted} jobId={jobId} onFix={fix} highlight={highlight} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ cards */

function CardHead({ label, action }: { label: ReactNode; action?: ReactNode }) {
  return (
    <div className="cvc-card__head">
      <h2 className="cvc-label">{label}</h2>
      {action}
    </div>
  );
}

function EditLink({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button type="button" className="cvc-link" onClick={onClick} aria-label={label}>
      Edit
    </button>
  );
}

const issueWord = (n: number) => (n === 1 ? "1 issue" : `${n} issues`);

/**
 * A section's issue count. With issues it is a button that shows them in the panel (IN-12);
 * `tone` is "warn" on cards and "bad" while the role is being edited.
 */
function IssueCount({
  count,
  about,
  tone = "warn",
  showNone = false,
  onShow,
}: {
  count: number;
  about: string;
  tone?: "warn" | "bad";
  showNone?: boolean;
  onShow: () => void;
}) {
  if (count === 0) return showNone ? <span className="cvc-chip cvc-chip--ok">No issues</span> : null;
  return (
    <button
      type="button"
      className={`cvc-chip cvc-chip--${tone} cvc-chip--button`}
      onClick={onShow}
      aria-label={`Show the ${issueWord(count)} for ${about}`}
    >
      {issueWord(count)}
    </button>
  );
}

function SaveRow({ onCancel, onSave, saveLabel = "Save" }: { onCancel: () => void; onSave: () => void; saveLabel?: string }) {
  return (
    <div className="row row--end cvc-save">
      <button type="button" className="btn btn--secondary" onClick={onCancel}>
        Cancel
      </button>
      <button type="button" className="btn" onClick={onSave}>
        {saveLabel}
      </button>
    </div>
  );
}

/** A textarea with Cancel and Save. Mounted when its card opens, so it starts from `initial`. */
function TextEditor({
  id,
  label,
  rows,
  hint,
  initial,
  flash,
  onCancel,
  onSave,
}: {
  id: string;
  label: string;
  rows: number;
  hint?: string;
  initial: string;
  flash?: string;
  onCancel: () => void;
  onSave: (text: string) => void;
}) {
  const [text, setText] = useState(initial);
  return (
    <div className="field">
      <label htmlFor={id} className="visually-hidden">
        {label}
      </label>
      <textarea
        id={id}
        rows={rows}
        value={text}
        aria-describedby={hint ? `${id}-hint` : undefined}
        data-flash={flash === id || undefined}
        onChange={(e) => setText(e.target.value)}
      />
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      <SaveRow onCancel={onCancel} onSave={() => onSave(text)} />
    </div>
  );
}

function SummaryCard({
  summary,
  open,
  setOpen,
  onSave,
  notes,
  flash,
  onShowIssues,
}: {
  summary: string;
  open: boolean;
  setOpen: (v: boolean) => void;
  onSave: (summary: string) => void;
  notes: ResumeIssue[];
  flash?: string;
  onShowIssues: (issues: ResumeIssue[]) => void;
}) {
  return (
    <section className="cvc-card" aria-labelledby="cvc-summary">
      <CardHead
        label={<span id="cvc-summary">Summary and intro</span>}
        action={
          <span className="cvc-card__actions">
            <IssueCount count={notes.length} about="the summary" onShow={() => onShowIssues(notes)} />
            {!open && <EditLink onClick={() => setOpen(true)} label="Edit the summary" />}
          </span>
        }
      />
      {open ? (
        <TextEditor
          id="cv-summary"
          label="Summary"
          rows={4}
          initial={summary}
          flash={flash}
          onCancel={() => setOpen(false)}
          onSave={(text) => {
            onSave(text);
            setOpen(false);
          }}
        />
      ) : summary.trim() ? (
        <p className="cvc-summary">{summary}</p>
      ) : (
        <p className="muted">No summary yet.</p>
      )}
      {notes.length > 0 && (
        <p className="cvc-note">
          ⚠ {notes.length === 1 ? "1 note" : `${notes.length} notes`}: {notes.map((n) => n.title.toLowerCase()).join("; ")}.{" "}
          <button type="button" className="cvc-link cvc-link--inline" onClick={() => onShowIssues(notes)}>
            See What we found
          </button>
        </p>
      )}
    </section>
  );
}

function RoleCard({
  role,
  today,
  collapsed,
  current,
  issueCount,
  onShowIssues,
  onShow,
  onEdit,
}: {
  role: CvRole;
  today: string;
  collapsed: boolean;
  current: boolean;
  issueCount: number;
  onShowIssues: () => void;
  onShow: () => void;
  onEdit: () => void;
}) {
  const name = `${role.title || "Untitled role"} · ${role.company || "Company not given"}`;
  const span = formatSpan(role.start || null, role.end || null, today);
  const headingId = `role-${role.key}-heading`;
  const edit = <EditLink onClick={onEdit} label={`Edit ${name}`} />;
  if (collapsed) {
    return (
      <section className="cvc-card cvc-role cvc-role--line" aria-labelledby={headingId}>
        <h3 id={headingId} className="cvc-role__line">
          <button type="button" className="cvc-role__toggle" aria-expanded={false} onClick={onShow}>
            {name}
          </button>
        </h3>
        <span className="cvc-role__meta">
          {role.start ? `${formatDate(role.start)} to ${role.end ? formatDate(role.end) : "now"}` : "No dates"}
          <IssueCount count={issueCount} about={name} onShow={onShowIssues} />
          {edit}
        </span>
      </section>
    );
  }
  return (
    <section className={`cvc-card cvc-role${current ? " cvc-role--current" : ""}`} aria-labelledby={headingId}>
      <div className="cvc-role__head">
        <div>
          <h3 id={headingId} className="cvc-role__title">
            {name}
          </h3>
          <p className="cvc-role__span">{span}</p>
        </div>
        <div className="cvc-role__actions">
          <IssueCount count={issueCount} about={name} showNone onShow={onShowIssues} />
          {edit}
        </div>
      </div>
      {role.achievements.some((a) => a.trim()) ? (
        <ul className="cvc-role__list">
          {role.achievements
            .filter((a) => a.trim())
            .map((a, j) => (
              <li key={j}>{a}</li>
            ))}
        </ul>
      ) : (
        <p className="muted">No achievements under this role.</p>
      )}
      {role.skills.length > 0 && (
        <ul className="cvc-chips" aria-label={`Skills at ${role.company || "this role"}`}>
          {role.skills.map((s) => (
            <li key={s} className="cvc-chip">
              {s}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RoleEditor({
  role,
  index,
  count,
  issues,
  allIssues,
  errors,
  others,
  flash,
  onChange,
  onShowIssues,
  onCancel,
  onSave,
  onRemove,
  onMove,
  onMoveAchievement,
}: {
  role: CvRole;
  index: number;
  count: number;
  /** Open issues whose Fix points at this role. */
  issues: ResumeIssue[];
  /** Every open issue about this role, for the chip. */
  allIssues: ResumeIssue[];
  errors: RoleErrors;
  others: CvRole[];
  flash?: string;
  onChange: (change: Partial<CvRole>) => void;
  onShowIssues: () => void;
  onCancel: () => void;
  onSave: () => void;
  onRemove: () => void;
  onMove: (by: -1 | 1) => void;
  onMoveAchievement: (item: number, toKey: number) => void;
}) {
  const id = `role-${role.key}`;
  const label = role.title.trim() || role.company.trim() ? `${role.title.trim() || "Role"} · ${role.company.trim() || "?"}` : "New role";
  const notesFor = (field: string) =>
    issues.filter((i) => i.target.section === "role" && i.target.field === field && i.fieldNote).map((i) => i.fieldNote!);
  const itemNotes = (j: number) =>
    issues.filter((i) => i.items?.includes(j) && i.fieldNote).map((i) => i.fieldNote!);
  const otherName = (r: CvRole) => `${r.title.trim() || "Role"} at ${r.company.trim() || "?"}`;

  const fields = [
    ["title", "Title", ""],
    ["company", "Company", ""],
    ["start", "Start", "YYYY or YYYY-MM"],
    ["end", "End", "Empty if current"],
  ] as const;

  return (
    <section className="cvc-card cvc-role cvc-role--editing" role="group" aria-labelledby={`${id}-legend`}>
      <div className="cvc-role__head">
        <h3 id={`${id}-legend`} className="cvc-role__title">
          Editing · {label}
        </h3>
        <IssueCount count={allIssues.length} about={label} tone="bad" onShow={onShowIssues} />
      </div>
      <div className="cvc-fields">
        {fields.map(([name, text, hint]) => {
          const fieldId = `${id}-${name}`;
          const error = errors[name];
          const notes = notesFor(name);
          const describedBy = [error && `${fieldId}-error`, notes.length && `${fieldId}-note`, hint && `${fieldId}-hint`]
            .filter(Boolean)
            .join(" ");
          return (
            <div className="field" key={name}>
              <label htmlFor={fieldId}>
                {text}
                {hint && (
                  <span className="hint" id={`${fieldId}-hint`}>
                    {" "}
                    ({hint})
                  </span>
                )}
              </label>
              <input
                id={fieldId}
                type="text"
                value={role[name]}
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy || undefined}
                data-flagged={notes.length > 0 || undefined}
                data-flash={flash === fieldId || undefined}
                onChange={(e) => onChange({ [name]: e.target.value })}
              />
              {error && (
                <p className="field-error" id={`${fieldId}-error`}>
                  {error}
                </p>
              )}
              {notes.length > 0 && (
                <p className="cvc-field-note" id={`${fieldId}-note`}>
                  {notes.join(". ")}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <h4 className="cvc-sub">Achievements</h4>
      <ol className="cvc-achievements">
        {role.achievements.map((text, j) => {
          const itemId = `${id}-achievement-${j}`;
          const notes = itemNotes(j);
          return (
            <li key={j} className="cvc-achievement" data-flagged={notes.length > 0 || undefined}>
              <label htmlFor={itemId} className="visually-hidden">
                Achievement {j + 1} at {label}
              </label>
              <textarea
                id={itemId}
                rows={2}
                value={text}
                aria-describedby={notes.length ? `${itemId}-note` : undefined}
                data-flash={flash === itemId || undefined}
                onChange={(e) => onChange({ achievements: role.achievements.map((a, k) => (k === j ? e.target.value : a)) })}
              />
              {notes.length > 0 && (
                <p className="cvc-field-note" id={`${itemId}-note`}>
                  {notes.join(". ")}
                </p>
              )}
              <div className="row cvc-achievement__actions">
                {others.length > 0 && (
                  <select
                    value=""
                    aria-label={`Move achievement ${j + 1} at ${label} to another role`}
                    onChange={(e) => {
                      if (e.target.value !== "") onMoveAchievement(j, Number(e.target.value));
                    }}
                  >
                    <option value="">Move to…</option>
                    {others.map((other) => (
                      <option key={other.key} value={other.key}>
                        {otherName(other)}
                      </option>
                    ))}
                  </select>
                )}
                <button
                  type="button"
                  className="cvc-link cvc-link--quiet"
                  aria-label={`Remove achievement ${j + 1} at ${label}`}
                  onClick={() => onChange({ achievements: role.achievements.filter((_, k) => k !== j) })}
                >
                  Remove
                </button>
              </div>
            </li>
          );
        })}
      </ol>
      <button
        type="button"
        className="cvc-link"
        onClick={() => onChange({ achievements: [...role.achievements, ""] })}
      >
        + Add an achievement
      </button>

      <div className="field cvc-role-skills">
        <label htmlFor={`${id}-skills`}>Skills used</label>
        <input
          id={`${id}-skills`}
          type="text"
          value={role.skills.join(", ")}
          aria-describedby={`${id}-skills-hint`}
          onChange={(e) => onChange({ skills: e.target.value.split(",").map((s) => s.trimStart()) })}
        />
        <p className="hint" id={`${id}-skills-hint`}>
          Separate skills with commas.
        </p>
      </div>

      <div className="cvc-editor-foot">
        <div className="row">
          <button
            type="button"
            id={`${id}-move-up`}
            className="cvc-link cvc-link--quiet"
            disabled={index === 0}
            onClick={() => onMove(-1)}
            aria-label={`Move ${label} up`}
          >
            ↑ Up
          </button>
          <button
            type="button"
            id={`${id}-move-down`}
            className="cvc-link cvc-link--quiet"
            disabled={index === count - 1}
            onClick={() => onMove(1)}
            aria-label={`Move ${label} down`}
          >
            ↓ Down
          </button>
          <button type="button" className="cvc-link cvc-link--danger" onClick={onRemove} aria-label={`Remove the role ${label}`}>
            Remove role
          </button>
        </div>
        <SaveRow onCancel={onCancel} onSave={onSave} saveLabel="Save role" />
      </div>
    </section>
  );
}

function SkillsCard({
  skills,
  open,
  setOpen,
  onSave,
  flash,
  issues,
  onShowIssues,
}: {
  skills: string[];
  open: boolean;
  setOpen: (v: boolean) => void;
  onSave: (skills: string[]) => void;
  flash?: string;
  issues: ResumeIssue[];
  onShowIssues: (issues: ResumeIssue[]) => void;
}) {
  const groups = skills.length > GROUP_SKILLS_OVER ? groupSkills(skills) : null;
  const chips = (list: string[]) => (
    <ul className="cvc-chips">
      {list.map((s) => (
        <li key={s} className="cvc-chip">
          {s}
        </li>
      ))}
    </ul>
  );
  return (
    <section className="cvc-card" aria-labelledby="cvc-skills">
      <CardHead
        label={<span id="cvc-skills">Skills · {skills.length}</span>}
        action={
          <span className="cvc-card__actions">
            <IssueCount count={issues.length} about="Skills" onShow={() => onShowIssues(issues)} />
            {!open && <EditLink onClick={() => setOpen(true)} label="Edit skills" />}
          </span>
        }
      />
      {open ? (
        <TextEditor
          id="cv-skills"
          label="Skills"
          rows={3}
          hint="Separate skills with commas."
          initial={skills.join(", ")}
          flash={flash}
          onCancel={() => setOpen(false)}
          onSave={(text) => {
            onSave(cleanList(splitList(text, /,/)));
            setOpen(false);
          }}
        />
      ) : skills.length === 0 ? (
        <p className="muted">No skills listed.</p>
      ) : groups ? (
        groups.map((g) => (
          <div key={g.group} className="cvc-skill-group">
            <h3 className="cvc-sub">{g.group}</h3>
            {chips(g.skills)}
          </div>
        ))
      ) : (
        chips(skills)
      )}
    </section>
  );
}

const emptyEducation = (): Education => ({ institution: "", degree: null, field_of_study: null, end: null });

function EducationCard({
  education,
  open,
  setOpen,
  onSave,
}: {
  education: Education[];
  open: boolean;
  setOpen: (v: boolean) => void;
  onSave: (education: Education[]) => void;
}) {
  return (
    <section className="cvc-card" aria-labelledby="cvc-education">
      <CardHead
        label={<span id="cvc-education">Education</span>}
        action={!open && <EditLink onClick={() => setOpen(true)} label="Edit education" />}
      />
      {open ? (
        <EducationEditor
          initial={education}
          onCancel={() => setOpen(false)}
          onSave={(rows) => {
            onSave(rows);
            setOpen(false);
          }}
        />
      ) : education.length === 0 ? (
        <p className="muted">No education listed.</p>
      ) : (
        education.map((e, i) => (
          <div key={i} className="cvc-edu">
            <b>{[e.degree, e.field_of_study].filter(Boolean).join(" ") || e.institution}</b>
            <p className="muted">
              {[e.degree || e.field_of_study ? e.institution : null, e.end ? formatDate(e.end) : null].filter(Boolean).join(" · ")}
            </p>
          </div>
        ))
      )}
    </section>
  );
}

function EducationEditor({
  initial,
  onCancel,
  onSave,
}: {
  initial: Education[];
  onCancel: () => void;
  onSave: (rows: Education[]) => void;
}) {
  const [rows, setRows] = useState<Education[]>(() => (initial.length ? initial.map((e) => ({ ...e })) : [emptyEducation()]));
  const set = (i: number, change: Partial<Education>) => setRows((r) => r.map((e, j) => (j === i ? { ...e, ...change } : e)));
  return (
    <div className="cvc-edu-edit">
      {rows.map((e, i) => (
        <fieldset key={i} className="cvc-edu-row">
          <legend className="visually-hidden">Education {i + 1}</legend>
          {(
            [
              ["institution", "School"],
              ["degree", "Degree"],
              ["field_of_study", "Field"],
              ["end", "Finished (YYYY)"],
            ] as const
          ).map(([name, text]) => (
            <div className="field" key={name}>
              <label htmlFor={`edu-${i}-${name}`}>{text}</label>
              <input
                id={`edu-${i}-${name}`}
                type="text"
                value={e[name] ?? ""}
                onChange={(ev) => set(i, { [name]: ev.target.value })}
              />
            </div>
          ))}
          <button
            type="button"
            className="cvc-link cvc-link--quiet"
            onClick={() => setRows((r) => r.filter((_, j) => j !== i))}
            aria-label={`Remove education ${i + 1}`}
          >
            Remove
          </button>
        </fieldset>
      ))}
      <button type="button" className="cvc-link" onClick={() => setRows((r) => [...r, emptyEducation()])}>
        + Add education
      </button>
      <SaveRow onCancel={onCancel} onSave={() => onSave(rows.filter((e) => e.institution.trim()))} />
    </div>
  );
}

function CertificationsCard({
  certifications,
  open,
  setOpen,
  onSave,
}: {
  certifications: string[];
  open: boolean;
  setOpen: (v: boolean) => void;
  onSave: (certifications: string[]) => void;
}) {
  return (
    <section className="cvc-card" aria-labelledby="cvc-certs">
      <CardHead
        label={<span id="cvc-certs">Certifications</span>}
        action={!open && <EditLink onClick={() => setOpen(true)} label="Edit certifications" />}
      />
      {open ? (
        <TextEditor
          id="cv-certifications"
          label="Certifications"
          rows={3}
          hint="One per line."
          initial={certifications.join("\n")}
          onCancel={() => setOpen(false)}
          onSave={(text) => {
            onSave(cleanList(splitList(text, /\n/)));
            setOpen(false);
          }}
        />
      ) : certifications.length === 0 ? (
        <p className="muted">No certifications listed.</p>
      ) : (
        <ul className="cvc-plain">
          {certifications.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ the issues panel */

const gapPracticePath = (gap: { from: string; to: string }, jobId: string) => {
  const ask = `Help me answer "tell me about this gap" for ${gap.from} to ${gap.to}.`;
  return `/coach/new?ask=${encodeURIComponent(ask)}${jobId ? `&job=${encodeURIComponent(jobId)}` : ""}`;
};

/** The label of the reason an issue was accepted with, if it is one of the issue's reasons. */
const acceptedReason = (issue: ResumeIssue, code: string | undefined) =>
  code ? (issue.reasons?.find((r) => r.code === code)?.label ?? null) : null;

function IssuesPanel({
  issues,
  accepted,
  jobId,
  onFix,
  highlight,
}: {
  issues: ResumeIssue[];
  accepted: AcceptedIssues;
  jobId: string;
  onFix: (issue: ResumeIssue) => void;
  highlight: Highlight | null;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  // On phones the panel sits above the CV, folded to its summary until opened.
  const [folded, setFolded] = useState(() => Boolean(globalThis.matchMedia?.("(max-width: 979px)").matches));
  const listRef = useRef<HTMLDivElement>(null);
  const lit = new Set(highlight?.keys ?? []);

  // A click on a section's issue count: show every issue and open the panel, once per click.
  const [seen, setSeen] = useState(0);
  if (highlight && highlight.n !== seen) {
    setSeen(highlight.n);
    setFilter("all");
    setFolded(false);
  }
  // Then scroll to the first of them.
  useEffect(() => {
    if (!highlight) return;
    const first = listRef.current?.querySelector<HTMLElement>("[data-highlight]");
    first?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    first?.querySelector<HTMLElement>("summary")?.focus();
  }, [highlight]);
  const openIssues = issues.filter((i) => !accepted.keys.has(i.key));
  const acceptedIssues = issues.filter((i) => accepted.keys.has(i.key));
  const counts: Record<Filter, number> = {
    all: openIssues.length,
    dates: openIssues.filter((i) => i.group === "dates").length,
    detail: openIssues.filter((i) => i.group === "detail").length,
    accepted: acceptedIssues.length,
  };
  const shown =
    filter === "accepted" ? [] : filter === "all" ? openIssues : openIssues.filter((i) => i.group === filter);
  const filters: [Filter, string][] = [
    ["all", "All"],
    ["dates", "Dates"],
    ["detail", "Detail"],
    ["accepted", "Accepted"],
  ];

  return (
    <aside className="cvc-panel" aria-labelledby="cvc-found" data-folded={folded || undefined}>
      <WhatWeCheck />
      <section className="cvc-card cvc-panel__head">
        <div className="cvc-card__head">
          <h2 id="cvc-found">What we found</h2>
          <span className="cvc-mono" aria-live="polite">
            {counts.all} open · {counts.accepted} accepted
          </span>
        </div>
        <div className="cvc-filters" role="group" aria-label="Show issues">
          {filters.map(([key, text]) => (
            <button
              key={key}
              type="button"
              className="cvc-filter"
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {text}
              {key !== "all" && ` ${counts[key]}`}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="cvc-link cvc-panel__toggle"
          aria-expanded={!folded}
          aria-controls="cvc-issue-list"
          onClick={() => setFolded((f) => !f)}
        >
          {folded ? "Show the issues" : "Hide the issues"}
        </button>
      </section>

      <div className="cvc-panel__list" id="cvc-issue-list" ref={listRef}>
      {accepted.error != null && <ErrorNotice error={accepted.error} title="We could not save that." />}
      {shown.length === 0 && filter !== "accepted" && (
        <p className="cvc-card cvc-clear">
          {filter === "all" ? "Nothing to fix. Your CV reads well." : `No ${filter === "dates" ? "date" : "detail"} issues.`}
        </p>
      )}
      {shown.map((issue, n) => (
        <IssueCard
          key={issue.key}
          issue={issue}
          defaultOpen={n < 2}
          highlighted={lit.has(issue.key)}
          jobId={jobId}
          onFix={() => onFix(issue)}
          onAccept={(reason) => accepted.accept(issue.key, reason)}
        />
      ))}
      {(filter === "all" || filter === "accepted") &&
        acceptedIssues.map((issue) => (
          <div key={issue.key} className="cvc-card cvc-accepted" data-highlight={lit.has(issue.key) || undefined}>
            <span>
              ✓ Accepted: {issue.title}
              {acceptedReason(issue, accepted.reasons.get(issue.key)) && (
                <span className="cvc-accepted__why"> · {acceptedReason(issue, accepted.reasons.get(issue.key))}</span>
              )}
            </span>
            <button
              type="button"
              className="cvc-link"
              onClick={() => accepted.undo(issue.key)}
              aria-label={`Undo accepting ${issue.title}`}
            >
              Undo
            </button>
          </div>
        ))}
      {filter === "accepted" && acceptedIssues.length === 0 && (
        <p className="cvc-card cvc-clear">Nothing accepted yet.</p>
      )}
      </div>
    </aside>
  );
}

/**
 * The list of checks, folded at the top of the issues column so it is seen without scrolling and
 * does not push the issues down.
 */
function WhatWeCheck() {
  return (
    <details className="cvc-card cvc-checks">
      <summary>What we check</summary>
        <ul>
          <li>
            <b>Dates:</b> gaps over 3 months, overlapping roles, end before start, future dates, years only, missing
            dates, current role not marked. Left old dates off on purpose? Accept it and say why.
          </li>
          <li>
            <b>Detail:</b> roles with fewer than 2 achievements, achievements with no result (a number, a measure that
            moved, or the scale), "we" with no "I", a very short or missing summary.
          </li>
          <li>
            <b>Fit for level:</b> a Senior target with no scope signals (team size, budget, cross-team work).
          </li>
          <li>
            <b>Consistency:</b> skills used in roles but missing from Skills, the same company listed twice.
          </li>
          <li>
            <b>Against a job:</b> when you check it for an interview, the job's must-have skills that your CV never shows.
          </li>
        </ul>
    </details>
  );
}

function IssueCard({
  issue,
  defaultOpen,
  highlighted,
  jobId,
  onFix,
  onAccept,
}: {
  issue: ResumeIssue;
  defaultOpen: boolean;
  /** Pointed at from a section's issue count: drawn highlighted and opened. */
  highlighted: boolean;
  jobId: string;
  onFix: () => void;
  onAccept: (reason?: string) => void;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (ref.current && defaultOpen) ref.current.open = true;
    // Only on mount: the user opens and closes it after that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (ref.current && highlighted) ref.current.open = true;
  }, [highlighted]);
  return (
    <details
      ref={ref}
      className="cvc-card cvc-issue"
      data-severity={issue.severity}
      data-group={issue.group}
      data-highlight={highlighted || undefined}
    >
      <summary>
        <span>
          <b>{issue.title}</b>
          <span className="cvc-issue__detail">{issue.detail}</span>
        </span>
        <span className="cvc-issue__group">{GROUP_LABEL[issue.group]}</span>
      </summary>
      <p className="cvc-issue__why">{issue.why}</p>
      <div className="row cvc-issue__actions">
        <button type="button" className="btn btn--small" onClick={onFix}>
          {issue.fixLabel}
        </button>
        <button type="button" className="btn btn--secondary btn--small" onClick={() => onAccept()}>
          {issue.acceptLabel}
        </button>
        {issue.reasons?.map((r) => (
          <button
            key={r.code}
            type="button"
            className="btn btn--secondary btn--small"
            onClick={() => onAccept(r.code)}
            aria-label={`Accept: ${r.label}`}
          >
            {r.label}
          </button>
        ))}
        {issue.gap && (
          <Link to={gapPracticePath(issue.gap, jobId)} className="cvc-practice">
            Practice "tell me about this gap"
          </Link>
        )}
      </div>
    </details>
  );
}
