import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { authApi } from "../api/auth";
import { keys } from "../api/hooks";
import { AuthHeading } from "../components/AuthLayout";
import { PasswordField, passwordProblem } from "../components/PasswordField";
import { ErrorNotice } from "../components/ui";

/** AC-5: the reset link from the email opens this page. A new password signs the user in. */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reset = useMutation({
    mutationFn: authApi.resetPassword,
    onSuccess: (state) => {
      queryClient.setQueryData(keys.me, state);
      navigate("/");
    },
  });

  if (!token) {
    return (
      <div className="auth-card">
        <AuthHeading title="Reset your password" />
        <div className="notice notice--error" role="alert">
          <p>This page needs the link from the reset email. Ask for a new one.</p>
        </div>
        <Link to="/signin">Back to sign in</Link>
      </div>
    );
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    // The email is not known here; the API also checks the email-name rule.
    const problem = passwordProblem(password, "");
    setError(problem);
    if (!problem) reset.mutate({ token, password });
  };

  return (
    <div className="auth-card">
      <AuthHeading title="Choose a new password" />
      <form onSubmit={onSubmit} noValidate>
        <PasswordField
          id="new-password"
          label="New password"
          value={password}
          onChange={setPassword}
          error={error}
          newPassword
        />
        {reset.isError && <ErrorNotice error={reset.error} />}
        <button type="submit" className="btn btn--block" disabled={reset.isPending}>
          Save password and sign in
        </button>
      </form>
      <p className="auth-switch">
        <Link to="/signin">Back to sign in</Link>
      </p>
    </div>
  );
}
