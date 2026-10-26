import { useWaitlist, waitlistApi, type AdminWaitlistEntry } from "../api/waitlist";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { utc } from "../format";
import { roleFamilyLabel } from "../labels";

const WHEN: Record<AdminWaitlistEntry["interview_within"], string> = {
  two_weeks: "Within 2 weeks",
  month: "Within a month",
  later: "Later",
  not_yet: "Not booked",
};

/** L04: people waiting for sign-ups to open, from the public waitlist page. */
export function WaitlistPage() {
  const waitlist = useWaitlist();

  return (
    <>
      <PageHead title="Waitlist">
        <p>People who joined from the public waitlist page. Only confirmed emails should get an invite.</p>
      </PageHead>
      <div className="row section-actions">
        <a className="btn" href={waitlistApi.csvUrl} download>
          Download CSV
        </a>
      </div>

      {waitlist.isPending && <Loading label="Loading the waitlist" />}
      {waitlist.isError && <ErrorNotice error={waitlist.error} />}
      {waitlist.data && (
        <>
          <div className="kpis">
            <div className="kpi">
              <p className="kpi__label">Joined</p>
              <p className="kpi__value">{waitlist.data.total}</p>
            </div>
            <div className="kpi">
              <p className="kpi__label">Confirmed</p>
              <p className="kpi__value">{waitlist.data.confirmed}</p>
            </div>
            <div className="kpi">
              <p className="kpi__label">Want product news</p>
              <p className="kpi__value">{waitlist.data.marketing_consent}</p>
            </div>
          </div>
          {waitlist.data.entries.length === 0 ? (
            <p className="section">No one has joined yet.</p>
          ) : (
            <div className="table-wrap section">
              <table aria-label="Waitlist entries">
                <thead>
                  <tr>
                    <th scope="col">Email</th>
                    <th scope="col">Interview</th>
                    <th scope="col">Field</th>
                    <th scope="col">Confirmed</th>
                    <th scope="col">News</th>
                    <th scope="col">Source</th>
                    <th scope="col">Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {waitlist.data.entries.map((e) => (
                    <tr key={e.id}>
                      <td>{e.email}</td>
                      <td>{WHEN[e.interview_within]}</td>
                      <td>{e.role_family ? roleFamilyLabel[e.role_family] : "-"}</td>
                      <td>{e.confirmed_at ? utc(e.confirmed_at) : "No"}</td>
                      <td>{e.marketing_consent ? "Yes" : "No"}</td>
                      <td>{e.source ?? "-"}</td>
                      <td>{utc(e.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
