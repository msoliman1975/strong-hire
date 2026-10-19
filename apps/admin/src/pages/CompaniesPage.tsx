import { useState } from "react";
import { Link } from "react-router";

import { useCompanies, useSetCompanyActive, type AdminCompany } from "../api/content";
import { ProfileImport } from "../components/ProfileImport";
import { ReasonDialog } from "../components/ReasonDialog";
import { ErrorNotice, Loading, PageHead } from "../components/ui";

/** AT-1: companies with their active flag, published version, open versions and requests. */
export function CompaniesPage() {
  const companies = useCompanies();
  const setActive = useSetCompanyActive();
  const [toggling, setToggling] = useState<AdminCompany | null>(null);
  const [importing, setImporting] = useState(false);

  return (
    <>
      <PageHead title="Companies">
        <p>Curated companies and their profile versions. Job matching only uses active companies.</p>
      </PageHead>
      <div className="row section-actions">
        <button type="button" className="btn" onClick={() => setImporting((v) => !v)} aria-expanded={importing}>
          {importing ? "Close import" : "Import a profile"}
        </button>
        <Link to="/content/requests">Company requests</Link>
      </div>
      {importing && <ProfileImport />}

      {companies.isPending && <Loading label="Loading companies" />}
      {companies.isError && <ErrorNotice error={companies.error} />}
      {companies.data && companies.data.length === 0 && <p>No companies yet. Run the seed.</p>}
      {companies.data && companies.data.length > 0 && (
        <div className="table-wrap section">
          <table>
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Active</th>
                <th scope="col" className="num">
                  Published
                </th>
                <th scope="col" className="num">
                  Drafts
                </th>
                <th scope="col" className="num">
                  In review
                </th>
                <th scope="col" className="num">
                  Requests
                </th>
              </tr>
            </thead>
            <tbody>
              {companies.data.map((c) => (
                <tr key={c.slug}>
                  <td>
                    <Link to={`/content/companies/${c.slug}`}>{c.name}</Link> <span className="muted">{c.slug}</span>
                  </td>
                  <td>
                    <span className="row row--tight">
                      {c.active ? "Yes" : "No"}
                      <button
                        type="button"
                        className="btn btn--small"
                        aria-label={`${c.active ? "Turn off" : "Turn on"} ${c.name}`}
                        onClick={() => {
                          setActive.reset();
                          setToggling(c);
                        }}
                      >
                        {c.active ? "Turn off" : "Turn on"}
                      </button>
                    </span>
                  </td>
                  <td className="num">{c.published_version ? `v${c.published_version}` : "-"}</td>
                  <td className="num">{c.draft_count}</td>
                  <td className="num">{c.in_review_count}</td>
                  <td className="num">{c.request_users}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {toggling && (
        <ReasonDialog
          title={`${toggling.active ? "Turn off" : "Turn on"} ${toggling.name}?`}
          confirmLabel={toggling.active ? "Turn off" : "Turn on"}
          danger={toggling.active}
          pending={setActive.isPending}
          error={setActive.error}
          onCancel={() => setToggling(null)}
          onConfirm={(reason) =>
            setActive.mutate(
              { slug: toggling.slug, active: !toggling.active, reason },
              { onSuccess: () => setToggling(null) },
            )
          }
        >
          <p>
            {toggling.active
              ? `Job setup stops matching ${toggling.name} (${toggling.slug}). New interviews for it use generic mode.`
              : `Job setup matches ${toggling.name} (${toggling.slug}) again and uses its published profile.`}
          </p>
        </ReasonDialog>
      )}
    </>
  );
}
