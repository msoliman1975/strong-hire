import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router";

import { authApi } from "../api/auth";
import { useAuth, useModelUsage, useUsage } from "../api/hooks";
import { ModelUsageBadge } from "./ModelUsageBadge";
import { ErrorNotice, Loading } from "./ui";
import { UsageMeter } from "./UsageMeter";

/** Shell for signed-in pages: header with navigation and usage meter. */
export function AppLayout() {
  const auth = useAuth();
  const location = useLocation();
  const signedIn = auth.data?.status === "signed_in";
  const usage = useUsage(signedIn);
  const modelUsage = useModelUsage(signedIn);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logout = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      queryClient.clear();
      navigate("/signin");
    },
  });

  if (auth.isPending) return <Loading label="Checking your sign-in" />;
  if (auth.isError) {
    return (
      <main className="page page--narrow">
        <ErrorNotice error={auth.error} title="The app cannot reach the server." />
      </main>
    );
  }
  if (auth.data.status === "signed_out") {
    return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  }
  if (auth.data.status === "needs_signup") return <Navigate to="/signup" replace />;

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <div className="app-header__inner">
          <Link className="brand" to="/">
            Strong Hire
          </Link>
          <nav className="app-nav" aria-label="Main">
            <ul>
              <li>
                <NavLink to="/" end>
                  Dashboard
                </NavLink>
              </li>
              <li>
                <NavLink to="/jobs/new">Add a job</NavLink>
              </li>
              <li>
                <NavLink to="/account">Account</NavLink>
              </li>
            </ul>
          </nav>
          <div className="app-header__end">
            <ModelUsageBadge usage={modelUsage.data} />
            {usage.data && <UsageMeter usage={usage.data} />}
            <button
              type="button"
              className="btn btn--quiet"
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main id="main" className="page">
        <Outlet />
      </main>
    </>
  );
}

/** Shell for the sign-in and sign-up pages. */
export function PublicLayout() {
  return (
    <>
      <header className="app-header">
        <div className="app-header__inner">
          <span className="brand">Strong Hire</span>
        </div>
      </header>
      <main id="main" className="page page--narrow">
        <Outlet />
      </main>
    </>
  );
}
