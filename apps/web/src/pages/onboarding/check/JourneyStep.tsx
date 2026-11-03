/**
 * RSD-9: step 1, "Your career journey". The editable resume as a timeline, newest first: the
 * summary, the roles on a rail with their gaps, then skills, education and certifications as three
 * tiles. Every edit works as before (IN-3); `ResumeCheckV2` owns the draft and the editors.
 */
import { useState, type ReactNode } from "react";

import {
  formatDate,
  formatSpan,
  groupSkills,
  GROUP_SKILLS_OVER,
  type ResumeIssue,
} from "../resumeChecks";
import { cleanList, OPEN_ROLES, splitList, type CvDraft, type CvRole, type Education, type RoleErrors } from "./draft";


/** "2015-03" as a month count; a year alone counts as its January. */
const monthIndex = (value: string): number | null => {
  const m = /^(\d{4})(?:-(\d{2}))?$/.exec(value.trim());
  return m ? Number(m[1]) * 12 + (m[2] ? Number(m[2]) - 1 : 0) : null;
};

/** The gap's length in months, from the dates of the two roles around it. */
export function gapMonths(newer: CvRole | undefined, older: CvRole | undefined): number | null {
  const start = newer ? monthIndex(newer.start) : null;
  const end = older ? monthIndex(older.end) : null;
  return start !== null && end !== null && start > end ? start - end : null;
}

/** "5-month gap · Mar 2015 to Aug 2015 · see the fix". */
export function gapLabel(issue: ResumeIssue, roles: CvRole[]): string {
  const target = issue.target.section === "role" ? issue.target.role : -1;
  const older = issue.roles.find((r) => r !== target);
  const months = gapMonths(roles[target], older === undefined ? undefined : roles[older]);
  const span = issue.gap ? `${issue.gap.from} to ${issue.gap.to}` : issue.detail;
  return `${months ? `${months}-month gap` : "A gap"} · ${span} · see the fix`;
}

export interface JourneyStepProps {
  draft: CvDraft;
  editing: Record<number, CvRole>;
  roleErrors: Record<number, RoleErrors>;
  openSection: Record<string, boolean>;
  setOpenSection: (name: string, open: boolean) => void;
  shown: ReadonlySet<number>;
  today: string;
  flash?: string;
  /** Open findings (not accepted). */
  open: ResumeIssue[];
  onSaveSummary: (summary: string) => void;
  onSaveSkills: (skills: string[]) => void;
  onSaveEducation: (education: Education[]) => void;
  onSaveCertifications: (certifications: string[]) => void;
  onShowRole: (key: number) => void;
  onEditRole: (role: CvRole) => void;
  onChangeRole: (key: number, change: Partial<CvRole>) => void;
  onCancelRole: (key: number) => void;
  onSaveRole: (key: number) => void;
  onRemoveRole: (key: number) => void;
  onMoveRole: (key: number, by: -1 | 1) => void;
  onMoveAchievement: (fromKey: number, item: number, toKey: number) => void;
  onAddRole: () => void;
  /** Opens the first of these findings in step 2. */
  onShowFindings: (list: ResumeIssue[]) => void;
  /** After the roles, before the tiles (the next step card). */
  footer?: ReactNode;
}

export function JourneyStep(props: JourneyStepProps) {
  const { draft, editing, open, flash } = props;
  const issuesFor = (index: number) => open.filter((i) => i.roles.includes(index));
  const gaps = open.filter((i) => i.gap && i.target.section === "role");
  return (
    <section className="cvc-step-view cvc-journey" aria-labelledby="cvc-journey-h">
      <div className="cvc-view-head">
        <h2 id="cvc-journey-h">Your career journey</h2>
        <p className="muted">What Strova read. Edit anything she got wrong.</p>
      </div>
      <ResumeSummaryCard
        summary={draft.summary}
        open={Boolean(props.openSection.summary)}
        setOpen={(v) => props.setOpenSection("summary", v)}
        onSave={props.onSaveSummary}
        notes={open.filter((i) => i.target.section === "summary")}
        flash={flash}
        onShowIssues={props.onShowFindings}
      />

      <p className="cvc-label cvc-label--section">
        Experience · {draft.roles.length} {draft.roles.length === 1 ? "role" : "roles"}
        {draft.roles.length > 1 ? " · newest first" : ""}
      </p>
      {draft.roles.length === 0 && <p className="muted">We found no roles in your resume. Add one if you want.</p>}
      {draft.roles.length > 0 && (
        <ol className="cvc-tl" aria-label="Roles, newest first">
          {draft.roles.map((role, index) => {
            const copy = editing[role.key];
            const roleIssues = issuesFor(index);
            const gap = gaps.find((g) => g.target.section === "role" && g.target.role === index);
            const last = index === draft.roles.length - 1;
            return (
              <li key={role.key} className="cvc-tl__item" data-gap={gap ? true : undefined}>
                <span className="cvc-tl__rail" aria-hidden="true">
                  <span className="cvc-tl__pin" />
                  {!last && <span className={`cvc-tl__line${gap ? " cvc-tl__line--gap" : ""}`} />}
                </span>
                <div className="cvc-tl__body">
                  {copy ? (
                    <RoleEditor
                      role={copy}
                      index={index}
                      count={draft.roles.length}
                      issues={roleIssues.filter((i) => i.target.section === "role" && i.target.role === index)}
                      allIssues={roleIssues}
                      errors={props.roleErrors[role.key] ?? {}}
                      others={draft.roles.filter((r) => r.key !== role.key).map((r) => editing[r.key] ?? r)}
                      flash={flash}
                      onChange={(change) => props.onChangeRole(role.key, change)}
                      onShowIssues={() => props.onShowFindings(roleIssues)}
                      onCancel={() => props.onCancelRole(role.key)}
                      onSave={() => props.onSaveRole(role.key)}
                      onRemove={() => props.onRemoveRole(role.key)}
                      onMove={(by) => props.onMoveRole(role.key, by)}
                      onMoveAchievement={(item, to) => props.onMoveAchievement(role.key, item, to)}
                    />
                  ) : (
                    <RoleCard
                      role={role}
                      today={props.today}
                      collapsed={index >= OPEN_ROLES && !props.shown.has(role.key)}
                      current={index === 0}
                      issueCount={roleIssues.length}
                      onShowIssues={() => props.onShowFindings(roleIssues)}
                      onShow={() => props.onShowRole(role.key)}
                      onEdit={() => props.onEditRole(role)}
                    />
                  )}
                  {gap && (
                    <button type="button" className="cvc-link cvc-gap-link" onClick={() => props.onShowFindings([gap])}>
                      {gapLabel(gap, draft.roles)}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      <button type="button" className="cvc-link cvc-add" onClick={props.onAddRole}>
        + Add a role
      </button>

      <div className="cvc-pair">
        <SkillsCard
          skills={draft.skills}
          open={Boolean(props.openSection.skills)}
          setOpen={(v) => props.setOpenSection("skills", v)}
          onSave={props.onSaveSkills}
          flash={flash}
          issues={open.filter((i) => i.target.section === "skills")}
          onShowIssues={props.onShowFindings}
        />
        <EducationCard
          education={draft.education}
          open={Boolean(props.openSection.education)}
          setOpen={(v) => props.setOpenSection("education", v)}
          onSave={props.onSaveEducation}
        />
        <CertificationsCard
          certifications={draft.certifications}
          open={Boolean(props.openSection.certifications)}
          setOpen={(v) => props.setOpenSection("certifications", v)}
          onSave={props.onSaveCertifications}
        />
      </div>
      {props.footer}
    </section>
  );
}


export function CardHead({ label, action }: { label: ReactNode; action?: ReactNode }) {
  return (
    <div className="cvc-card__head">
      <h2 className="cvc-label">{label}</h2>
      {action}
    </div>
  );
}

export function EditLink({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button type="button" className="cvc-link" onClick={onClick} aria-label={label}>
      Edit
    </button>
  );
}

const findingWord = (n: number) => (n === 1 ? "1 finding" : `${n} findings`);

/**
 * RSD-9: a section's "{n} finding(s)" chip. With findings it is a button that opens the first of
 * them in Strova's findings (IN-12); `tone` is "warn" on cards and "bad" while the role is edited.
 */
export function IssueCount({
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
  if (count === 0) return showNone ? <span className="cvc-chip cvc-chip--ok">No findings</span> : null;
  return (
    <button
      type="button"
      className={`cvc-chip cvc-chip--${tone} cvc-chip--button`}
      onClick={onShow}
      aria-label={`Show the ${findingWord(count)} for ${about}`}
    >
      {findingWord(count)}
    </button>
  );
}

export function SaveRow({ onCancel, onSave, saveLabel = "Save" }: { onCancel: () => void; onSave: () => void; saveLabel?: string }) {
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
export function TextEditor({
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

export function ResumeSummaryCard({
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
            See Strova's findings
          </button>
        </p>
      )}
    </section>
  );
}

export function RoleCard({
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

export function RoleEditor({
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

export function SkillsCard({
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

export function EducationCard({
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

export function EducationEditor({
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

export function CertificationsCard({
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

