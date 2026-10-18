import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { authApi } from "../api/auth";
import { keys, useAuth, useProviders } from "../api/hooks";
import { useSiteStatus } from "../api/status";
import type { AuthState, EmailSent } from "../api/types";
import { AuthHeading } from "../components/AuthLayout";
import { PasswordField, passwordProblem } from "../components/PasswordField";
import { ErrorNotice, Loading } from "../components/ui";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const EMAIL_ERROR = "Enter an email address, for example name@example.com.";

/** OC-1: the API refuses new accounts with the same words. */
const SIGNUPS_PAUSED =
  "We are not taking new sign-ups right now. Write to support@getstronghire.com to join the waitlist, and we will email you when we open again.";

const LINK_ERRORS: Record<string, string> = {
  link_expired: "That link has expired. Ask for a new one.",
  link_used: "That link was already used. Ask for a new one.",
  link_invalid: "That link is not valid. Ask for a new one.",
  google: "Google sign-in did not finish. Try again, or use your email and password.",
  signups_paused: SIGNUPS_PAUSED,
};

type Mode = "signin" | "signup" | "link" | "forgot";

const TITLES: Record<Mode, string> = {
  signin: "Sign in",
  signup: "Create an account",
  link: "Email me a sign-in link",
  forgot: "Reset your password",
};

function DevLink({ sent, label }: { sent: EmailSent | null; label: string }) {
  if (!sent?.dev_link) return null;
  return (
    <p className="auth-dev-link">
      Local development: <a href={sent.dev_link}>{label}</a>.
    </p>
  );
}

function EmailField({ value, onChange, error }: { value: string; onChange: (v: string) => void; error?: string }) {
  return (
    <div className="field">
      <label htmlFor="email">Email address</label>
      <input
        id="email"
        type="email"
        autoComplete="email"
        placeholder="name@example.com"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? "email-error" : undefined}
      />
      {error && (
        <p id="email-error" className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}

/** Sign in and Create an account, as two tabs over one form area. */
function ModeTabs({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const tabs: Mode[] = ["signin", "signup"];
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = mode === "signin" ? "signup" : "signin";
    onChange(next);
    document.getElementById(`tab-${next}`)?.focus();
  };
  return (
    <div className="auth-tabs" role="tablist" aria-label="Account">
      {tabs.map((t) => (
        <button
          key={t}
          id={`tab-${t}`}
          type="button"
          role="tab"
          aria-selected={mode === t}
          aria-controls="auth-panel"
          tabIndex={mode === t ? 0 : -1}
          onClick={() => onChange(t)}
          onKeyDown={onKey}
        >
          {t === "signin" ? "Sign in" : "Create account"}
        </button>
      ))}
    </div>
  );
}

function Sent({ children, onBack }: { children: ReactNode; onBack: () => void }) {
  return (
    <div className="auth-card">
      <AuthHeading title="Check your email" />
      <div role="status">{children}</div>
      <button type="button" className="btn btn--quiet auth-back" onClick={onBack}>
        Back to sign in
      </button>
    </div>
  );
}

type Errors = { email?: string; password?: string; agreed?: string };

export function SignInPage() {
  const auth = useAuth();
  const providers = useProviders();
  const siteStatus = useSiteStatus();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [mode, setMode] = useState<Mode>(params.get("mode") === "signup" ? "signup" : "signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [sent, setSent] = useState<{ kind: "link" | "reset"; reply: EmailSent } | null>(null);
  const [devEmail, setDevEmail] = useState("dev@example.com");

  const signedIn = (state: AuthState) => {
    queryClient.setQueryData(keys.me, state);
    navigate(state.status === "signed_in" ? "/" : "/signup");
  };

  const login = useMutation({ mutationFn: authApi.passwordLogin, onSuccess: signedIn });
  // AC-4: sign-up signs the user in at once; the confirmation email follows.
  const signup = useMutation({ mutationFn: authApi.passwordSignup, onSuccess: signedIn });
  const magicLink = useMutation({
    mutationFn: authApi.sendMagicLink,
    onSuccess: (reply) => setSent({ kind: "link", reply }),
  });
  const forgot = useMutation({
    mutationFn: authApi.forgotPassword,
    onSuccess: (reply) => setSent({ kind: "reset", reply }),
  });
  const devLogin = useMutation({ mutationFn: authApi.devLogin, onSuccess: signedIn });

  if (auth.isPending) return <Loading label="Checking your sign-in" />;
  if (auth.data?.status === "signed_in") return <Navigate to="/" replace />;
  if (auth.data?.status === "needs_signup") return <Navigate to="/signup" replace />;

  const cleanEmail = email.trim();
  const switchMode = (next: Mode) => {
    setMode(next);
    setErrors({});
    setSent(null);
    for (const m of [login, signup, magicLink, forgot]) m.reset();
  };
  const emailError = () => (EMAIL_RE.test(cleanEmail) ? undefined : EMAIL_ERROR);

  const onSignIn = (e: FormEvent) => {
    e.preventDefault();
    const next: Errors = { email: emailError(), password: password ? undefined : "Enter your password." };
    setErrors(next);
    if (next.email || next.password) return;
    login.mutate({ email: cleanEmail, password });
  };

  const onSignUp = (e: FormEvent) => {
    e.preventDefault();
    const next: Errors = {
      email: emailError(),
      password: passwordProblem(password, cleanEmail) ?? undefined,
      agreed: agreed ? undefined : "Confirm that you are 18 or older and accept the terms.",
    };
    setErrors(next);
    if (next.email || next.password || next.agreed) return;
    signup.mutate({
      email: cleanEmail,
      password,
      full_name: fullName.trim() || null,
      age_confirmed: true,
      terms_accepted: true,
    });
  };

  const onEmailOnly = (e: FormEvent) => {
    e.preventDefault();
    const next: Errors = { email: emailError() };
    setErrors(next);
    if (next.email) return;
    (mode === "link" ? magicLink : forgot).mutate(cleanEmail);
  };

  if (sent) {
    const back = () => switchMode("signin");
    if (sent.kind === "reset") {
      return (
        <Sent onBack={back}>
          <p>
            If <strong>{cleanEmail}</strong> has a Strong Hire account, we sent it a link to choose a new password. It
            works once, for 30 minutes.
          </p>
          <DevLink sent={sent.reply} label="open the reset link" />
        </Sent>
      );
    }
    return (
      <Sent onBack={back}>
        <p>
          We sent a sign-in link to <strong>{cleanEmail}</strong>. It works once, for 15 minutes.
        </p>
        <DevLink sent={sent.reply} label="open the sign-in link" />
      </Sent>
    );
  }

  const linkError = params.get("error");
  const tabbed = mode === "signin" || mode === "signup";

  return (
    <div className="auth-card">
      {params.get("deleted") === "1" && (
        <div className="notice notice--ok" role="status">
          <p>Your account deletion has started. All your data is removed within 24 hours.</p>
        </div>
      )}
      {params.get("confirmed") === "1" && (
        <div className="notice notice--ok" role="status">
          <p>Your email is confirmed. Sign in with your password.</p>
        </div>
      )}
      {linkError && (
        <div className="notice notice--error" role="alert">
          <p>{LINK_ERRORS[linkError] ?? "Sign-in did not finish. Try again."}</p>
        </div>
      )}
      {auth.isError && <ErrorNotice error={auth.error} title="The app cannot reach the server." />}

      <AuthHeading title={TITLES[mode]} hidden={tabbed} />
      {tabbed && <ModeTabs mode={mode} onChange={switchMode} />}

      <div id="auth-panel" role={tabbed ? "tabpanel" : undefined} aria-labelledby={tabbed ? `tab-${mode}` : undefined}>
        {mode === "signin" && (
          <form onSubmit={onSignIn} noValidate>
            <EmailField value={email} onChange={setEmail} error={errors.email} />
            <PasswordField
              id="password"
              label="Password"
              value={password}
              onChange={setPassword}
              error={errors.password}
              extra={
                <button type="button" className="link-button link-button--small" onClick={() => switchMode("forgot")}>
                  Forgot password?
                </button>
              }
            />
            {login.isError && <ErrorNotice error={login.error} />}
            <button type="submit" className="btn btn--block" disabled={login.isPending}>
              Sign in
            </button>
          </form>
        )}

        {mode === "signup" && siteStatus.data?.signups_open === false && (
          <div className="notice" role="status">
            <p>{SIGNUPS_PAUSED}</p>
          </div>
        )}
        {mode === "signup" && (
          <form onSubmit={onSignUp} noValidate>
            <EmailField value={email} onChange={setEmail} error={errors.email} />
            <div className="field">
              <label htmlFor="full-name">Your name (optional)</label>
              <input
                id="full-name"
                type="text"
                autoComplete="name"
                maxLength={120}
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>
            <PasswordField
              id="new-password"
              label="Password"
              value={password}
              onChange={setPassword}
              error={errors.password}
              newPassword
              email={cleanEmail}
            />
            <div className="check">
              <input
                id="agree"
                type="checkbox"
                checked={agreed}
                onChange={(e) => setAgreed(e.target.checked)}
                aria-invalid={errors.agreed ? true : undefined}
                aria-describedby={errors.agreed ? "agree-error" : undefined}
              />
              <div>
                <label htmlFor="agree">I am 18 or older, and I accept the terms of service and the privacy policy.</label>
                {errors.agreed && (
                  <p id="agree-error" className="field-error">
                    {errors.agreed}
                  </p>
                )}
              </div>
            </div>
            {signup.isError && <ErrorNotice error={signup.error} />}
            <button type="submit" className="btn btn--block" disabled={signup.isPending}>
              Create account
            </button>
            <p className="auth-fine">We also email you a link to confirm your address.</p>
          </form>
        )}

        {!tabbed && (
          <form onSubmit={onEmailOnly} noValidate>
            <p className="muted">
              {mode === "link"
                ? "We email you a link that signs you in. No password needed."
                : "We email you a link to choose a new password."}
            </p>
            <EmailField value={email} onChange={setEmail} error={errors.email} />
            {mode === "link" && magicLink.isError && <ErrorNotice error={magicLink.error} />}
            {mode === "forgot" && forgot.isError && <ErrorNotice error={forgot.error} />}
            <button
              type="submit"
              className="btn btn--block"
              disabled={mode === "link" ? magicLink.isPending : forgot.isPending}
            >
              {mode === "link" ? "Email me a sign-in link" : "Email me a reset link"}
            </button>
            <button type="button" className="btn btn--quiet auth-back" onClick={() => switchMode("signin")}>
              Back to sign in
            </button>
          </form>
        )}
      </div>

      {mode === "signin" && (
        <>
          <div className="auth-alt">
            <span className="auth-alt__or">or</span>
            <button type="button" className="btn btn--secondary btn--block" onClick={() => switchMode("link")}>
              Email me a sign-in link instead
            </button>
            {providers.data?.google && (
              <a className="btn btn--secondary btn--block" href={authApi.googleLoginUrl}>
                Continue with Google
              </a>
            )}
          </div>
          <p className="auth-switch">
            New to Strong Hire?{" "}
            <button type="button" className="link-button" onClick={() => switchMode("signup")}>
              Create an account
            </button>
          </p>
        </>
      )}
      {mode === "signup" && (
        <p className="auth-switch">
          Already have an account?{" "}
          <button type="button" className="link-button" onClick={() => switchMode("signin")}>
            Sign in
          </button>
        </p>
      )}

      {providers.data?.dev && mode === "signin" && (
        <section className="auth-dev" aria-labelledby="dev-heading">
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
  );
}
