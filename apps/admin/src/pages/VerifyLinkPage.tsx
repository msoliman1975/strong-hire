import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { authApi } from "../api/auth";
import { ApiError } from "../api/client";
import { keys } from "../api/hooks";
import { Brand } from "../components/Brand";
import { Loading, PageHead } from "../components/ui";
import { LINK_ERRORS } from "./SignInPage";

/**
 * Where an admin sign-in email lands (AA-2): /signin/verify?token=... posts the token to the API,
 * which starts the admin session. The link is used by this page, not by opening it, so a mail
 * scanner that fetches the URL does not use it up.
 */
export function VerifyLinkPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const verify = useMutation({
    mutationFn: authApi.verifyLink,
    onSuccess: (me) => {
      queryClient.setQueryData(keys.me, me);
      navigate("/", { replace: true });
    },
  });
  const started = useRef(false);

  useEffect(() => {
    // Once only: React may run effects twice in development, and a link works once.
    if (started.current || !token) return;
    started.current = true;
    verify.mutate(token);
  }, [token, verify]);

  const code = verify.error instanceof ApiError ? verify.error.message : "link_invalid";
  const failed = !token || verify.isError;

  return (
    <main id="main" className="centered">
      <div className="card card--signin">
        <Brand />
        <PageHead title="Signing in" />
        {!failed && <Loading label="Checking your sign-in link" />}
        {failed && (
          <>
            <div className="notice notice--error" role="alert">
              <p>{LINK_ERRORS[code] ?? LINK_ERRORS.link_invalid}</p>
            </div>
            <p>
              <Link to="/signin">Back to sign-in</Link>
            </p>
          </>
        )}
      </div>
    </main>
  );
}
