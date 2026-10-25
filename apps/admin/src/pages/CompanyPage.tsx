import { useState } from "react";
import { Link, useParams } from "react-router";

import {
  NEXT_STATUSES,
  useCompanyProfiles,
  useProfileDiff,
  useProfileVersion,
  useTransition,
  type AdminCompany,
  type ProfileVersion,
  type TransitionTo,
} from "../api/content";
import { DiffView, type DiffMode } from "../components/DiffView";
import { ProfileDetails, type ProfileView } from "../components/ProfileDetails";
import { ProfileImport } from "../components/ProfileImport";
import { ReasonDialog } from "../components/ReasonDialog";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc, words } from "../format";

interface Pending {
  version: ProfileVersion;
  to: TransitionTo;
}

function actionLabel(from: ProfileVersion["status"], to: TransitionTo): string {
  if (to === "published") return from === "archived" ? "Roll back to this" : "Publish";
  if (to === "in_review") return "Send to review";
  if (to === "draft") return "Back to draft";
  return "Archive";
}

/** AA-7: the dialog repeats the company and the version, and what happens to the live one. */
function confirmText(company: AdminCompany, p: Pending): string {
  const target = `${company.name} (${company.slug}) version ${p.version.version}`;
  const live = company.published_version;
  if (p.to === "published") {
    const then = live ? ` Version ${live}, published now, becomes archived.` : "";
    return `New interviews for ${company.name} will use ${target}.${then}`;
  }
  if (p.to === "archived") {
    return `${target} stops being used. ${company.name} has no published profile until you publish one, so new interviews use generic mode.`;
  }
  return `${target} moves to ${words(p.to)}.`;
}

export function CompanyPage() {
  const { slug = "" } = useParams();
  const profiles = useCompanyProfiles(slug);
  const transition = useTransition();
  const [pending, setPending] = useState<Pending | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [pair, setPair] = useState<{ a: number | null; b: number | null } | null>(null);
  const [mode, setMode] = useState<DiffMode>("side");
  const [importing, setImporting] = useState(false);

  if (profiles.isPending) return <Loading label="Loading company" />;
  if (profiles.isError) return <ErrorNotice error={profiles.error} title="Could not load this company." />;

  const { company, versions } = profiles.data;
  const numbers = versions.map((v) => v.version);
  const latest = numbers.at(-1) ?? null;
  const fallbackA = company.published_version && company.published_version !== latest
    ? company.published_version
    : (numbers.at(-2) ?? null);
  const a = pair ? pair.a : fallbackA;
  const b = pair ? pair.b : latest;
  // AT-7: open on the live profile, or the newest one when nothing is published.
  const shown = viewing ?? company.published_version ?? latest;

  return (
    <>
      <p>
        <Link to="/content/companies">All companies</Link>
      </p>
      <PageHead title={company.name}>
        <p>
          {company.slug} · {company.active ? "Active" : "Not active"} · Published:{" "}
          {company.published_version ? `version ${company.published_version}` : "none (generic mode)"} ·{" "}
          {company.request_users} requesting users
        </p>
      </PageHead>

      {shown !== null && <VersionViewer slug={company.slug} version={shown} status={versions.find((v) => v.version === shown)?.status} />}

      <section className="section" aria-labelledby="versions">
        <div className="row row--between">
          <h2 id="versions">Profile versions</h2>
          <button type="button" className="btn btn--small" onClick={() => setImporting((v) => !v)} aria-expanded={importing}>
            {importing ? "Close import" : "Import a new version"}
          </button>
        </div>
        {importing && <ProfileImport slug={company.slug} />}
        {versions.length === 0 ? (
          <p>No profile versions yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Version</th>
                  <th scope="col">Status</th>
                  <th scope="col">Imported</th>
                  <th scope="col">Published</th>
                  <th scope="col">Reviewer</th>
                  <th scope="col" className="num">
                    Sources
                  </th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {[...versions].reverse().map((v) => (
                  <tr key={v.version} aria-current={shown === v.version ? "true" : undefined}>
                    <td>v{v.version}</td>
                    <td>
                      <span className="profile-status" data-status={v.status}>
                        {words(v.status)}
                      </span>
                    </td>
                    <td>{utc(v.imported_at)}</td>
                    <td>{utc(v.published_at)}</td>
                    <td>{v.reviewed_by ?? "-"}</td>
                    <td className="num">{v.source_count}</td>
                    <td>
                      <span className="row row--tight">
                        <button type="button" className="btn btn--small" onClick={() => {
                            setViewing(v.version);
                            document.getElementById("viewer")?.scrollIntoView?.({ behavior: "smooth" });
                          }}>
                          View v{v.version}
                        </button>
                        {NEXT_STATUSES[v.status].map((to) => (
                          <button
                            key={to}
                            type="button"
                            className={to === "published" ? "btn btn--small btn--primary" : "btn btn--small"}
                            aria-label={`${actionLabel(v.status, to)} v${v.version}`}
                            onClick={() => {
                              transition.reset();
                              setPending({ version: v, to });
                            }}
                          >
                            {actionLabel(v.status, to)}
                          </button>
                        ))}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {versions.length > 1 && (
        <section className="section" aria-labelledby="diff">
          <h2 id="diff">Compare versions</h2>
          <div className="filters">
            <VersionSelect label="Old version" value={a} numbers={numbers} onChange={(n) => setPair({ a: n, b })} />
            <VersionSelect label="New version" value={b} numbers={numbers} onChange={(n) => setPair({ a, b: n })} />
            <div className="field">
              <span className="label">View</span>
              <div className="row row--tight" role="group" aria-label="Diff view">
                <button type="button" className="btn btn--small" aria-pressed={mode === "side"} onClick={() => setMode("side")}>
                  Side by side
                </button>
                <button type="button" className="btn btn--small" aria-pressed={mode === "inline"} onClick={() => setMode("inline")}>
                  Inline
                </button>
              </div>
            </div>
          </div>
          <Diff slug={company.slug} a={a} b={b} mode={mode} />
        </section>
      )}

      {pending && (
        <ReasonDialog
          title={`${actionLabel(pending.version.status, pending.to)}: ${company.name} version ${pending.version.version}?`}
          confirmLabel={`${actionLabel(pending.version.status, pending.to)} ${company.slug} v${pending.version.version}`}
          danger={pending.to === "published" || pending.to === "archived"}
          pending={transition.isPending}
          error={transition.error}
          onCancel={() => setPending(null)}
          onConfirm={(reason) =>
            transition.mutate(
              { slug: company.slug, version: pending.version.version, to: pending.to, reason },
              { onSuccess: () => setPending(null) },
            )
          }
        >
          <p>{confirmText(company, pending)}</p>
        </ReasonDialog>
      )}
    </>
  );
}

function VersionSelect({
  label,
  value,
  numbers,
  onChange,
}: {
  label: string;
  value: number | null;
  numbers: number[];
  onChange: (n: number) => void;
}) {
  const id = `diff-${label.replace(/\s/g, "-").toLowerCase()}`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))}>
        {numbers.map((n) => (
          <option key={n} value={n}>
            Version {n}
          </option>
        ))}
      </select>
    </div>
  );
}

function Diff({ slug, a, b, mode }: { slug: string; a: number | null; b: number | null; mode: DiffMode }) {
  const diff = useProfileDiff(slug, a, b);
  if (a === null || b === null) return null;
  if (a === b) return <p className="muted">Pick two different versions.</p>;
  if (diff.isPending) return <Loading label="Comparing versions" />;
  if (diff.isError) return <ErrorNotice error={diff.error} />;
  return <DiffView diff={diff.data} mode={mode} />;
}

interface SourceView {
  url: string;
  title?: string | null;
  retrieved_at?: string;
  fields?: string[];
}

/** AT-2, AT-7: one version as readable sections, with its sources and the stored JSON. */
function VersionViewer({ slug, version, status }: { slug: string; version: number; status?: ProfileVersion["status"] }) {
  const detail = useProfileVersion(slug, version);
  return (
    <section className="section" aria-labelledby="viewer">
      <div className="row row--tight">
        <h2 id="viewer">Profile details: version {version}</h2>
        {status && (
          <span className="profile-status" data-status={status}>
            {words(status)}
          </span>
        )}
      </div>
      {detail.isPending && <Loading label="Loading version" />}
      {detail.isError && <ErrorNotice error={detail.error} />}
      {detail.data && (
        <>
          {detail.data.problems.length > 0 && (
            <div className="notice notice--error" role="alert">
              <p className="label">The stored JSON no longer matches the schema. It cannot be published.</p>
              <ul className="problems">
                {detail.data.problems.map((p) => (
                  <li key={p}>
                    <code>{p}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <ProfileDetails profile={detail.data.profile as ProfileView} />
          <h3>Sources ({detail.data.sources.length})</h3>
          <ol className="sources">
            {(detail.data.sources as SourceView[]).map((s) => (
              <li key={s.url}>
                <a href={s.url} target="_blank" rel="noreferrer noopener">
                  {s.title || s.url}
                </a>
                {s.retrieved_at && <span className="muted"> · retrieved {s.retrieved_at}</span>}
                {s.fields && s.fields.length > 0 && <span className="muted"> · {s.fields.join(", ")}</span>}
              </li>
            ))}
          </ol>
          <details>
            <summary>Profile JSON</summary>
            <pre className="json-view" aria-label={`Profile JSON of version ${version}`}>
              {JSON.stringify(detail.data.profile, null, 2)}
            </pre>
          </details>
        </>
      )}
    </section>
  );
}
