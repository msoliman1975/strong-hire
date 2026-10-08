import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";

import { authApi } from "../api/auth";
import { keys, useAuth } from "../api/hooks";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { ConsentCheckbox } from "../components/ConsentSwitch";

/** Sign-up: 18+ confirmation, terms, and the training-data consent (AC-2, off by default). */
export function SignupPage() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [adult, setAdult] = useState(false);
  const [terms, setTerms] = useState(false);
  const [consent, setConsent] = useState(false);
  const [showErrors, setShowErrors] = useState(false);

  const signup = useMutation({
    mutationFn: authApi.signup,
    onSuccess: (state) => {
      queryClient.setQueryData(keys.me, state);
      navigate("/");
    },
  });

  if (auth.isPending) return <Loading label="Checking your sign-in" />;
  if (auth.isError) return <ErrorNotice error={auth.error} title="The app cannot reach the server." />;
  if (auth.data.status === "signed_in") return <Navigate to="/" replace />;
  if (auth.data.status === "signed_out") return <Navigate to="/signin" replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!adult || !terms) {
      setShowErrors(true);
      return;
    }
    signup.mutate({ age_confirmed: adult, terms_accepted: terms, training_consent: consent });
  };

  return (
    <>
      <PageHead title="Create your account">
        <p>
          You are signing up as <strong>{auth.data.email}</strong>.
        </p>
      </PageHead>
      <form className="panel" onSubmit={onSubmit} noValidate>
        <div className="check">
          <input
            id="adult"
            type="checkbox"
            checked={adult}
            onChange={(e) => setAdult(e.target.checked)}
            aria-invalid={showErrors && !adult ? true : undefined}
            aria-describedby={showErrors && !adult ? "adult-error" : undefined}
          />
          <div>
            <label htmlFor="adult">I am 18 or older.</label>
            {showErrors && !adult && (
              <p id="adult-error" className="field-error">
                You must be 18 or older to use Strong Hire.
              </p>
            )}
          </div>
        </div>
        <div className="check">
          <input
            id="terms"
            type="checkbox"
            checked={terms}
            onChange={(e) => setTerms(e.target.checked)}
            aria-invalid={showErrors && !terms ? true : undefined}
            aria-describedby={showErrors && !terms ? "terms-error" : undefined}
          />
          <div>
            <label htmlFor="terms">I accept the terms of service and the privacy policy.</label>
            {showErrors && !terms && (
              <p id="terms-error" className="field-error">
                Accept the terms to create an account.
              </p>
            )}
          </div>
        </div>

        <div className="section">
          <ConsentCheckbox checked={consent} onChange={setConsent} />
        </div>

        {signup.isError && <ErrorNotice error={signup.error} />}
        <div className="row section">
          <button type="submit" className="btn" disabled={signup.isPending}>
            Create account
          </button>
        </div>
      </form>
    </>
  );
}
