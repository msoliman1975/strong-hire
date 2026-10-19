import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { authApi } from "../api/auth";
import { keys, useAuth, useProviders } from "../api/hooks";
import type { AdminLinkSent, AdminMe } from "../api/types";
import { Brand } from "../components/Brand";
import { ErrorNotice, Loading, PageHead } from "../components/ui";

export const LINK_ERRORS: Record<string, string> = {
  link_expired: "That link has expired. Ask for a new one.",
  link_used: "That link was already used. Ask for a new one.",
  link_invalid: "That link is not valid. Ask for a new one.",
  account_unavailable: "This account is not available. Contact support for help.",
  google: "Google sign-in did not finish. Try again, or use your email.",
  not_admin: "That Google account may not use the admin app.",
};

type Method = "password" | "link";

/**
 * Admin sign-in (AA-2): email and password, an email link, or Google, through the admin app's
 * own /admin/auth routes. Only active admins get a session (AA-1); the link reply is the same for
 * everyone, so the screen does not say who is an admin.
 */
export function SignInPage() {
  const auth = useAuth();
  const providers = useProviders();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [method, setMethod] = useState<Method>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sent, setSent] = useState<AdminLinkSent | null>(null);

  const signedIn = (me: AdminMe) => {
    queryClient.setQueryData(keys.me, me);
    navigate("/", { replace: true });
  };
  const login = useMutation({ mutationFn: authApi.passwordLogin, onSuccess: signedIn });
  const magicLink = useMutation({ mutationFn: authApi.sendMagicLink, onSuccess: setSent });

  if (auth.data) return <Navigate to="/" replace />;

  const linkError = params.get("error");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (method === "password") login.mutate({ email: email.trim(), password });
    else magicLink.mutate(email.trim());
  };

  return (
    <main id="main" className="centered">
      <div className="card card--signin">
        <Brand />
        <PageHead title="Admin sign-in">
          <p className="muted">For Strong Hire staff only.</p>
        </PageHead>

        {linkError && (
          <div className="notice notice--error" role="alert">
            <p>{LINK_ERRORS[linkError] ?? "Sign-in did not finish. Try again."}</p>
          </div>
        )}
        {auth.isPending && <Loading label="Checking your sign-in" />}
        {auth.isError && <ErrorNotice error={auth.error} title="The admin app cannot reach the server." />}

        {sent ? (
          <div className="notice" role="status">
            <p>If that email may use the admin app, a sign-in link is on its way. Open it in this browser.</p>
            {sent.dev_link && (
              <p>
                Local development: <a href={sent.dev_link}>open the sign-in link</a>.
              </p>
            )}
          </div>
        ) : (
          <form onSubmit={submit} aria-label="Sign in">
            <div className="field">
              <label htmlFor="email">Email address</label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            {method === "password" && (
              <div className="field">
                <label htmlFor="password">Password</label>
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
            )}
            {method === "password" && login.isError && <ErrorNotice error={login.error} />}
            {method === "link" && magicLink.isError && <ErrorNotice error={magicLink.error} />}
            <button
              type="submit"
              className="btn btn--primary btn--block"
              disabled={login.isPending || magicLink.isPending}
            >
              {method === "password" ? "Sign in" : "Email me a sign-in link"}
            </button>
            <button
              type="button"
              className="btn btn--link"
              onClick={() => setMethod(method === "password" ? "link" : "password")}
            >
              {method === "password" ? "Sign in with an email link instead" : "Sign in with a password instead"}
            </button>
          </form>
        )}

        {providers.data?.google && (
          <p>
            <a className="btn btn--block" href={authApi.googleLoginUrl}>
              Sign in with Google
            </a>
          </p>
        )}
      </div>
    </main>
  );
}
