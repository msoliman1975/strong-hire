import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import type { RoleFamily } from "../api/types";
import { waitlistApi, type InterviewWithin } from "../api/waitlist";
import { ErrorNotice, HireSignalScale, Loading, PageHead } from "../components/ui";
import { roleFamilyLabel } from "../labels";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const WHEN: { value: InterviewWithin; label: string }[] = [
  { value: "two_weeks", label: "In the next two weeks" },
  { value: "month", label: "Within a month" },
  { value: "later", label: "Later than that" },
  { value: "not_yet", label: "No interview booked yet" },
];

/** L04 step 1: join the waitlist. Public, no account. */
export function WaitlistPage() {
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [when, setWhen] = useState<InterviewWithin | null>(null);
  const [role, setRole] = useState<RoleFamily | "">("");
  const [marketing, setMarketing] = useState(false);
  const [website, setWebsite] = useState("");
  const [showErrors, setShowErrors] = useState(false);

  const join = useMutation({ mutationFn: waitlistApi.join });
  const emailOk = EMAIL_RE.test(email.trim());

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!emailOk || !when) {
      setShowErrors(true);
      return;
    }
    join.mutate({
      email: email.trim(),
      interview_within: when,
      role_family: role || null,
      marketing_consent: marketing,
      source: params.get("utm_source")?.slice(0, 100) || null,
      website: website || null,
    });
  };

  if (join.isSuccess) {
    return (
      <>
        <PageHead title="Check your email">
          <p>
            We sent a link to <strong>{email.trim()}</strong>. Open it to confirm your place on the waitlist. It
            works for 7 days.
          </p>
        </PageHead>
        <p className="muted">No email after a few minutes? Check your spam folder, or join again to get a new link.</p>
      </>
    );
  }

  return (
    <>
      <PageHead title="Find out if you'd get the offer, before the interview">
        <p>
          Strong Hire is a voice interviewer that rehearses your real job at your real company, then tells you what
          the hiring committee would decide, with quotes from your answers. Join the waitlist and we'll email you
          when sign-ups open.
        </p>
      </PageHead>

      <ol className="waitlist-steps" aria-label="How it works">
        <li>
          <strong>Paste the job posting and your CV.</strong> You get a free gap analysis of where you match.
        </li>
        <li>
          <strong>Practice by voice.</strong> The interviewer follows up on vague answers, like a real one.
        </li>
        <li>
          <strong>Get the verdict.</strong> A hire signal, a rubric per question, and what to fix first.
        </li>
      </ol>

      <form className="panel waitlist-form" onSubmit={onSubmit} noValidate aria-labelledby="waitlist-title">
        <h2 id="waitlist-title">Join the waitlist</h2>
        <div className="field">
          <label htmlFor="waitlist-email">Email</label>
          <input
            id="waitlist-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={showErrors && !emailOk ? true : undefined}
            aria-describedby={showErrors && !emailOk ? "waitlist-email-error" : undefined}
          />
          {showErrors && !emailOk && (
            <p id="waitlist-email-error" className="field-error">
              Enter an email address, for example name@example.com.
            </p>
          )}
        </div>

        <fieldset className="field" aria-describedby={showErrors && !when ? "waitlist-when-error" : undefined}>
          <legend>When is your interview?</legend>
          {WHEN.map((w) => (
            <div className="check" key={w.value}>
              <input
                id={`when-${w.value}`}
                type="radio"
                name="interview_within"
                checked={when === w.value}
                onChange={() => setWhen(w.value)}
              />
              <label htmlFor={`when-${w.value}`}>{w.label}</label>
            </div>
          ))}
          {showErrors && !when && (
            <p id="waitlist-when-error" className="field-error">
              Choose one, so we can invite people with interviews soonest first.
            </p>
          )}
        </fieldset>

        <div className="field">
          <label htmlFor="waitlist-role">Your field (optional)</label>
          <select id="waitlist-role" value={role} onChange={(e) => setRole(e.target.value as RoleFamily | "")}>
            <option value="">Choose one</option>
            {(Object.keys(roleFamilyLabel) as RoleFamily[]).map((r) => (
              <option key={r} value={r}>
                {roleFamilyLabel[r]}
              </option>
            ))}
          </select>
        </div>

        <div className="check">
          <input id="waitlist-marketing" type="checkbox" checked={marketing} onChange={(e) => setMarketing(e.target.checked)} />
          <label htmlFor="waitlist-marketing">
            Also send me interview tips and product news. You can unsubscribe at any time.
          </label>
        </div>

        {/* Honeypot: hidden from people, filled by bots. */}
        <div className="visually-hidden" aria-hidden="true">
          <label htmlFor="waitlist-website">Website</label>
          <input
            id="waitlist-website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
          />
        </div>

        {join.isError && <ErrorNotice error={join.error} />}
        <div className="row section">
          <button type="submit" className="btn" disabled={join.isPending}>
            Join the waitlist
          </button>
        </div>
        <p className="muted small">
          Without the box above, we only email you to confirm this request and when sign-ups open. To be removed,
          write to support@getstronghire.com.
        </p>
      </form>

      <section className="panel verdict waitlist-sample" aria-labelledby="sample-title">
        <h2 id="sample-title">What you get after each interview</h2>
        <HireSignalScale signal="Lean Hire" />
        <blockquote className="waitlist-quote">
          "I owned the migration end to end and cut checkout errors by 40 percent." Strong ownership. The answer
          never says what you would do differently, which the bar for this level expects.
        </blockquote>
        <p className="muted small">An example debrief. Strong Hire is not affiliated with any company.</p>
      </section>

      <p className="muted">
        Already have an account? <Link to="/signin">Sign in</Link>
      </p>
    </>
  );
}

/** L04 step 1: the link from the confirmation email. */
export function WaitlistConfirmPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const confirm = useMutation({ mutationFn: waitlistApi.confirm });
  const sent = useRef(false);

  useEffect(() => {
    if (token && !sent.current) {
      sent.current = true;
      confirm.mutate(token);
    }
  }, [token, confirm]);

  if (!token || confirm.isError) {
    return (
      <PageHead title="This link doesn't work">
        <p>
          It may be older than 7 days or copied only in part. <Link to="/waitlist">Join the waitlist again</Link> to
          get a new link.
        </p>
      </PageHead>
    );
  }
  if (!confirm.isSuccess) return <Loading label="Confirming your email" />;
  return (
    <PageHead title="You're on the list">
      <p>Thanks for confirming. We'll email you when sign-ups open. People with interviews soonest go first.</p>
    </PageHead>
  );
}
