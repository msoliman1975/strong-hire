import { useEffect, useRef } from "react";
import { Outlet } from "react-router";

import { BrandMark, CheckBadge } from "./BrandMark";

/** The page title. Focus moves to it when the view changes, so screen readers announce it. */
export function AuthHeading({ title, hidden = false }: { title: string; hidden?: boolean }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} | Strong Hire`;
    ref.current?.focus();
  }, [title]);
  return (
    <h1 ref={ref} tabIndex={-1} className={hidden ? "visually-hidden" : "auth-title"}>
      {title}
    </h1>
  );
}

/** The practice loop on the sign-in page. Only the goal is green: it is the earned verdict. */
const LOOP = ["Rehearse interviews", "Scored", "Improve"];

const SAMPLE_SIGNALS = [
  { name: "Problem framing", label: "Strong", width: 88, color: "var(--signal-strong)" },
  { name: "Trade-off reasoning", label: "Positive", width: 72, color: "var(--signal-positive)" },
  { name: "Failure modes", label: "Mixed", width: 50, color: "var(--signal-neutral)" },
  { name: "Communication", label: "Strong", width: 84, color: "var(--signal-strong)" },
];

/**
 * Sign-in, sign-up and password reset: the form on white on the left, and on the slate stage on
 * the right, what practice leads to (option C of the sign-in design review).
 */
export function AuthLayout() {
  return (
    <div className="auth-screen">
      <main id="main" className="auth-screen__main">
        <span className="brand brand--auth">
          <BrandMark size={30} />
          <span className="brand__name">Strong Hire</span>
        </span>
        <div className="auth-screen__form">
          <Outlet />
        </div>
        <p className="auth-screen__help">
          Trouble signing in? Write to <span className="nowrap">support@getstronghire.com</span>
        </p>
      </main>
      <aside className="auth-stage" aria-label="How practice works">
        <p className="auth-stage__title">Practice until it reads Strong Hire.</p>
        <ol className="practice-loop">
          {LOOP.map((step) => (
            <li key={step} className="practice-loop__step">
              {step}
            </li>
          ))}
          <li className="practice-loop__step practice-loop__step--repeat">
            <span className="practice-loop__icon" aria-hidden="true">
              ↻
            </span>
            Repeat
          </li>
          <li className="practice-loop__step practice-loop__step--goal">
            <CheckBadge size={20} />
            Get Strong Hire
          </li>
        </ol>
        <figure className="sample-debrief" aria-label="Sample debrief">
          <div className="sample-debrief__top">
            <div>
              <p className="sample-debrief__role">Senior Backend Engineer · Stripe</p>
              <p className="sample-debrief__meta">System design · 45 min · Sample</p>
            </div>
            <span className="sample-debrief__verdict">
              <CheckBadge size={20} />
              Hire
            </span>
          </div>
          <ul className="sample-debrief__signals">
            {SAMPLE_SIGNALS.map((s) => (
              <li key={s.name}>
                <span>{s.name}</span>
                <span className="sample-debrief__label">{s.label}</span>
                <span className="sample-debrief__bar" aria-hidden="true">
                  <span style={{ width: `${s.width}%`, background: s.color }} />
                </span>
              </li>
            ))}
          </ul>
          <figcaption className="sample-debrief__note">
            <strong>Interviewer note:</strong> Clear idempotency story for retries. Probe deeper on partial
            failures between ledger and payout.
          </figcaption>
        </figure>
      </aside>
    </div>
  );
}
