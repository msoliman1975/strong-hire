import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { authApi } from "../api/auth";
import { keys, useAuth, useProviders } from "../api/hooks";
import type { AuthState, MagicLinkSent } from "../api/types";
import { ErrorNotice, Loading, PageHead } from "../components/ui";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const LINK_ERRORS: Record<string, string> = {
  link_expired: "That sign-in link has expired. Ask for a new one.",
  link_used: "That sign-in link was already used. Ask for a new one.",
  link_invalid: "That sign-in link is not valid. Ask for a new one.",
  google: "Google sign-in did not finish. Try again, or use an email link.",
};

export function SignInPage() {
  const auth = useAuth();
  const providers = useProviders();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [sent, setSent] = useState<MagicLinkSent | null>(null);
  const [devEmail, setDevEmail] = useState("dev@example.com");

  const magicLink = useMutation({ mutationFn: authApi.sendMagicLink, onSuccess: setSent });
  const devLogin = useMutation({
    mutationFn: authApi.devLogin,
    onSuccess: (state: AuthState) => {
      queryClient.setQueryData(keys.me, state);
      navigate(state.status === "signed_in" ? "/" : "/signup");
    },
  });

  if (auth.isPending) return <Loading label="Checking your sign-in" />;
  if (auth.data?.status === "signed_in") return <Navigate to="/" replace />;
  if (auth.data?.status === "needs_signup") return <Navigate to="/signup" replace />;

  const onEmailSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!EMAIL_RE.test(email.trim())) {
      setEmailError("Enter an email address, for example name@example.com.");
      return;
    }
    setEmailError(null);
    magicLink.mutate(email.trim());
  };

  const linkError = params.get("error");
  const deleted = params.get("deleted") === "1";

  return (
    <>
      <PageHead title="Sign in">
        <p>Practice a real interview for a specific job, then see how a hiring committee would judge it.</p>
      </PageHead>

      {deleted && (
        <div className="notice notice--ok" role="status">
          <p>Your account deletion has started. All your data is removed within 24 hours.</p>
        </div>
      )}
      {linkError && (
        <div className="notice notice--error" role="alert">
          <p>{LINK_ERRORS[linkError] ?? "Sign-in did not finish. Try again."}</p>
        </div>
      )}
      {auth.isError && <ErrorNotice error={auth.error} title="The app cannot reach the server." />}

      <div className="stack">
        {providers.data?.google && (
          <section className="panel" aria-labelledby="google-heading">
            <h2 id="google-heading">Google</h2>
            <a className="btn btn--secondary" href={authApi.googleLoginUrl}>
              Continue with Google
            </a>
          </section>
        )}

        <section className="panel" aria-labelledby="email-heading">
          <h2 id="email-heading">Email link</h2>
          {sent ? (
            <div role="status">
              <p>
                We sent a sign-in link to <strong>{email.trim()}</strong>. It works once, for 15 minutes.
              </p>
              {sent.dev_link && (
                <p>
                  Local development: <a href={sent.dev_link}>open the sign-in link</a>.
                </p>
              )}
              <button type="button" className="btn btn--quiet" onClick={() => setSent(null)}>
                Use a different email
              </button>
            </div>
          ) : (
            <form onSubmit={onEmailSubmit} noValidate>
              <div className="field">
                <label htmlFor="email">Email address</label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={emailError ? true : undefined}
                  aria-describedby={emailError ? "email-error" : undefined}
                />
                {emailError && (
                  <p id="email-error" className="field-error">
                    {emailError}
                  </p>
                )}
              </div>
              {magicLink.isError && <ErrorNotice error={magicLink.error} />}
              <button type="submit" className="btn" disabled={magicLink.isPending}>
                Email me a sign-in link
              </button>
            </form>
          )}
        </section>

        {providers.data?.dev && (
          <section className="panel" aria-labelledby="dev-heading">
            <h2 id="dev-heading">Dev login</h2>
            <p className="muted">Local development only. Signs in any email with no check.</p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                devLogin.mutate(devEmail.trim());
              }}
            >
              <div className="field">
                <label htmlFor="dev-email">Email for dev login</label>
                <input id="dev-email" type="text" value={devEmail} onChange={(e) => setDevEmail(e.target.value)} />
              </div>
              {devLogin.isError && <ErrorNotice error={devLogin.error} />}
              <button type="submit" className="btn btn--secondary" disabled={devLogin.isPending}>
                Sign in as dev user
              </button>
            </form>
          </section>
        )}
      </div>
    </>
  );
}
