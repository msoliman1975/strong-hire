/**
 * AT-7: one profile version shown as readable sections instead of raw JSON. The stored JSON may
 * be older than the schema (AT-2 lists its problems), so every field is optional here.
 */
import { Fragment } from "react";

import { interviewTypeLabel, levelLabel, roleFamilyLabel } from "../labels";
import { words } from "../format";
import type { InterviewType, RoleFamily } from "../api/types";
import type { SimLevel } from "../api/sim";

interface Principle {
  name?: string;
  description?: string;
  evidence_signals?: string[];
  weight?: number;
}

interface Round {
  name?: string;
  interview_type?: string | null;
  duration_min?: number | null;
  interviewer_role?: string | null;
  notes?: string | null;
}

interface Loop {
  role_family?: string;
  levels?: string[];
  rounds?: Round[];
}

interface Pattern {
  interview_type?: string;
  theme?: string;
  pattern?: string;
  competencies?: string[];
  values?: string[];
}

interface Sample {
  interview_type?: string;
  question?: string;
  strong_answer?: string;
  competencies?: string[];
  values?: string[];
  source_url?: string;
  role_families?: string[];
  levels?: string[];
}

interface LevelBar {
  level_name?: string;
  normalized_level?: string;
  role_family?: string | null;
  scope_expectation?: string;
}

export interface ProfileView {
  company_name?: string;
  meta?: { version?: number; status?: string; reviewed_by?: string | null; researched_at?: string | null };
  values_framework?: { name?: string; principles?: Principle[] };
  loop_structure?: Loop[];
  question_patterns?: Pattern[];
  sample_questions?: Sample[];
  bar_by_level?: LevelBar[];
  persona?: { tone?: string; pace?: string; pushback_style?: string; closing_style?: string };
  scoring_weights?: Record<string, number>;
  values_share?: number;
  case_style?: { product_sense?: number; estimation?: number; system_thinking?: number; notes?: string | null };
  field_confidence?: Record<string, string>;
  low_confidence_notes?: string[];
}

/** Confidence shown with the shared state colors: high is ok, medium needs a look, low is a flag. */
const CONFIDENCE_STATE: Record<string, string> = { high: "ok", medium: "pending", low: "firing" };

function typeLabel(t: string | null | undefined): string {
  if (!t) return "-";
  return interviewTypeLabel[t as InterviewType] ?? words(t);
}

function family(f: string | null | undefined): string {
  if (!f) return "All";
  return roleFamilyLabel[f as RoleFamily] ?? words(f);
}

function level(l: string | undefined): string {
  if (!l) return "-";
  return levelLabel[l as SimLevel] ?? words(l);
}

function list(items: string[] | undefined, label: (v: string) => string = words): string {
  return items && items.length > 0 ? items.map(label).join(", ") : "-";
}

function pct(share: number | undefined): string {
  return share === undefined ? "-" : `${Math.round(share * 100)}%`;
}

export function ProfileDetails({ profile }: { profile: ProfileView }) {
  const principles = profile.values_framework?.principles ?? [];
  const loops = profile.loop_structure ?? [];
  const patterns = profile.question_patterns ?? [];
  const samples = profile.sample_questions ?? [];
  const bars = profile.bar_by_level ?? [];
  const weights = Object.entries(profile.scoring_weights ?? {});
  const confidence = Object.entries(profile.field_confidence ?? {});
  const notes = profile.low_confidence_notes ?? [];
  const persona = profile.persona;
  const caseStyle = profile.case_style;

  return (
    <div className="profile">
      <section className="profile__part" aria-labelledby="p-summary">
        <h3 id="p-summary">Summary</h3>
        <dl className="dl panel">
          <dt>Researched</dt>
          <dd>{profile.meta?.researched_at ?? "-"}</dd>
          <dt>Reviewer</dt>
          <dd>{profile.meta?.reviewed_by ?? "Not reviewed"}</dd>
          <dt>Values framework</dt>
          <dd>
            {profile.values_framework?.name ?? "-"} ({principles.length} principles)
          </dd>
          <dt>Values share of the signal</dt>
          <dd>{pct(profile.values_share)}</dd>
          <dt>Content</dt>
          <dd>
            {loops.length} loops, {patterns.length} question patterns, {samples.length} sample questions,{" "}
            {bars.length} level bars
          </dd>
          {confidence.length > 0 && (
            <>
              <dt>Confidence</dt>
              <dd>
                <span className="row row--tight">
                  {confidence.map(([field, level]) => (
                    <span key={field} className="badge badge--state" data-state={CONFIDENCE_STATE[level] ?? "pending"}>
                      {words(field)}: {level}
                    </span>
                  ))}
                </span>
              </dd>
            </>
          )}
        </dl>
        {notes.length > 0 && (
          <div className="notice">
            <p className="label">Flagged for the reviewer</p>
            <ul className="problems">
              {notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="profile__part" aria-labelledby="p-values">
        <h3 id="p-values">{profile.values_framework?.name ?? "Values"}</h3>
        {principles.length === 0 ? (
          <p className="muted">No principles.</p>
        ) : (
          <div className="table-wrap">
            <table aria-labelledby="p-values">
              <thead>
                <tr>
                  <th scope="col">Principle</th>
                  <th scope="col">What it means</th>
                  <th scope="col">Evidence that sounds like it</th>
                  <th scope="col" className="num">
                    Weight
                  </th>
                </tr>
              </thead>
              <tbody>
                {principles.map((p) => (
                  <tr key={p.name}>
                    <td>
                      <strong>{p.name}</strong>
                    </td>
                    <td>{p.description}</td>
                    <td>
                      {p.evidence_signals && p.evidence_signals.length > 0 ? (
                        <ul className="profile__list">
                          {p.evidence_signals.map((s) => (
                            <li key={s}>{s}</li>
                          ))}
                        </ul>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="num">{p.weight ?? "1"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="profile__part" aria-labelledby="p-loops">
        <h3 id="p-loops">Interview loops</h3>
        {loops.length === 0 && <p className="muted">No loops.</p>}
        {loops.map((loop) => (
          <div key={loop.role_family} className="table-wrap">
            <table aria-label={`Loop for ${family(loop.role_family)}`}>
              <caption className="profile__caption">
                {family(loop.role_family)}
                {loop.levels && loop.levels.length > 0 && <span className="muted"> · levels {loop.levels.join(", ")}</span>}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Round</th>
                  <th scope="col">Type</th>
                  <th scope="col" className="num">
                    Minutes
                  </th>
                  <th scope="col">Interviewer</th>
                  <th scope="col">Notes</th>
                </tr>
              </thead>
              <tbody>
                {(loop.rounds ?? []).map((r, i) => (
                  <tr key={`${r.name}-${i}`}>
                    <td>{r.name}</td>
                    <td>{typeLabel(r.interview_type)}</td>
                    <td className="num">{r.duration_min ?? "-"}</td>
                    <td>{r.interviewer_role ?? "-"}</td>
                    <td>{r.notes ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </section>

      <section className="profile__part" aria-labelledby="p-levels">
        <h3 id="p-levels">Bar by level</h3>
        {bars.length === 0 ? (
          <p className="muted">No level bars.</p>
        ) : (
          <div className="table-wrap">
            <table aria-labelledby="p-levels">
              <thead>
                <tr>
                  <th scope="col">Level</th>
                  <th scope="col">Maps to</th>
                  <th scope="col">Role family</th>
                  <th scope="col">Scope expected</th>
                </tr>
              </thead>
              <tbody>
                {bars.map((b, i) => (
                  <tr key={`${b.level_name}-${b.role_family}-${i}`}>
                    <td>
                      <strong>{b.level_name}</strong>
                    </td>
                    <td>{level(b.normalized_level)}</td>
                    <td>{family(b.role_family)}</td>
                    <td>{b.scope_expectation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid-2">
        <section className="profile__part" aria-labelledby="p-persona">
          <h3 id="p-persona">Interviewer persona</h3>
          <dl className="dl panel">
            <dt>Tone</dt>
            <dd>{persona?.tone ?? "-"}</dd>
            <dt>Pace</dt>
            <dd>{persona?.pace ?? "-"}</dd>
            <dt>Pushback</dt>
            <dd>{persona?.pushback_style ?? "-"}</dd>
            <dt>Closing</dt>
            <dd>{persona?.closing_style ?? "-"}</dd>
          </dl>
        </section>
        <section className="profile__part" aria-labelledby="p-scoring">
          <h3 id="p-scoring">Scoring</h3>
          <dl className="dl panel">
            {weights.length === 0 && (
              <>
                <dt>Competency weights</dt>
                <dd>-</dd>
              </>
            )}
            {weights.map(([c, w]) => (
              <Fragment key={c}>
                <dt>{words(c)}</dt>
                <dd>{w}</dd>
              </Fragment>
            ))}
            <dt>Case style</dt>
            <dd>
              {caseStyle
                ? `Product sense ${pct(caseStyle.product_sense)}, estimation ${pct(caseStyle.estimation)}, system thinking ${pct(caseStyle.system_thinking)}`
                : "-"}
              {caseStyle?.notes && <span className="muted"> · {caseStyle.notes}</span>}
            </dd>
          </dl>
        </section>
      </div>

      <section className="profile__part" aria-labelledby="p-patterns">
        <h3 id="p-patterns">Question patterns ({patterns.length})</h3>
        {patterns.length === 0 ? (
          <p className="muted">No question patterns.</p>
        ) : (
          <div className="table-wrap">
            <table aria-labelledby="p-patterns">
              <thead>
                <tr>
                  <th scope="col">Type</th>
                  <th scope="col">Theme</th>
                  <th scope="col">Pattern</th>
                  <th scope="col">Probes</th>
                </tr>
              </thead>
              <tbody>
                {patterns.map((p, i) => (
                  <tr key={`${p.theme}-${i}`}>
                    <td>{typeLabel(p.interview_type)}</td>
                    <td>{p.theme}</td>
                    <td>{p.pattern}</td>
                    <td>{list([...(p.competencies ?? []), ...(p.values ?? [])])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="profile__part" aria-labelledby="p-samples">
        <h3 id="p-samples">Sample questions ({samples.length})</h3>
        {samples.length === 0 ? (
          <p className="muted">No sample questions.</p>
        ) : (
          <ol className="profile__questions panel">
            {samples.map((q, i) => (
              <li key={`${q.question}-${i}`}>
                <details>
                  <summary>
                    <span className="muted">{typeLabel(q.interview_type)} · </span>
                    {q.question}
                  </summary>
                  <dl className="dl">
                    <dt>Strong answer</dt>
                    <dd>{q.strong_answer ?? "-"}</dd>
                    <dt>Probes</dt>
                    <dd>{list([...(q.competencies ?? []), ...(q.values ?? [])])}</dd>
                    <dt>Fits</dt>
                    <dd>
                      {q.role_families?.length ? list(q.role_families, family) : "All roles"} ·{" "}
                      {q.levels?.length ? list(q.levels, level) : "all levels"}
                    </dd>
                    <dt>Source</dt>
                    <dd>
                      {q.source_url ? (
                        <a href={q.source_url} target="_blank" rel="noreferrer noopener">
                          {q.source_url}
                        </a>
                      ) : (
                        "-"
                      )}
                    </dd>
                  </dl>
                </details>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
