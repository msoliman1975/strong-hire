import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useMatch, useNavigate } from "react-router";

import { authApi } from "../api/auth";
import { useAuth, useModelUsage, useUsage } from "../api/hooks";
import { hasSlogan, SLOGAN } from "../labels";
import { BrandMark } from "./BrandMark";
import { ModelUsageBadge } from "./ModelUsageBadge";
import { ErrorNotice, Loading } from "./ui";
import { UsageMeter } from "./UsageMeter";

/** Logo, name and (once agreed) the slogan. A link on signed-in pages, plain text elsewhere. */
function Brand({ link }: { link: boolean }) {
  const inner = (
    <>
      <BrandMark size={30} tone="stage" />
      <span className="brand__name">Strong Hire</span>
      {hasSlogan(SLOGAN) && <span className="brand__slogan">{SLOGAN}</span>}
    </>
  );
  return link ? (
    <Link className="brand" to="/" aria-label="Strong Hire, your interviews">
      {inner}
    </Link>
  ) : (
    <span className="brand">{inner}</span>
  );
}

/** Initials button that opens a small menu with the account page and sign out. */
function AccountMenu({ email, onSignOut, busy }: { email: string; onSignOut: () => void; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const initials = email.slice(0, 2).toUpperCase() || "ME";

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <div className="account-menu" ref={ref}>
      <button
        type="button"
        className="account-menu__button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Account menu"
        onClick={() => setOpen((o) => !o)}
      >
        {initials}
      </button>
      {open && (
        <ul className="account-menu__list">
          {email && <li className="account-menu__email">{email}</li>}
          <li>
            <Link to="/account" onClick={() => setOpen(false)}>
              Account
            </Link>
          </li>
          <li>
            <button type="button" onClick={onSignOut} disabled={busy}>
              Sign out
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}

/** Shell for signed-in pages: the stage header with the menu, usage meter and account menu. */
export function AppLayout() {
  const auth = useAuth();
  const location = useLocation();
  const live = useMatch("/sessions/:sessionId/live") !== null;
  const signedIn = auth.data?.status === "signed_in";
  const usage = useUsage(signedIn);
  const modelUsage = useModelUsage(signedIn);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPath, setMenuPath] = useState(location.pathname);
  const logout = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      queryClient.clear();
      navigate("/signin");
    },
  });

  // The small-screen menu closes on every route change and on Escape.
  if (menuPath !== location.pathname) {
    setMenuPath(location.pathname);
    setMenuOpen(false);
  }
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

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

  // During a live interview the menu is hidden, so nothing pulls the candidate away from the session.
  if (live) {
    return (
      <>
        <header className="app-header">
          <div className="app-header__inner">
            <Brand link={false} />
            <span className="live-bar__status">
              <span className="live-dot" aria-hidden="true" />
              Live interview
            </span>
          </div>
        </header>
        <main id="main" className="page">
          <Outlet />
        </main>
      </>
    );
  }

  const email = auth.data.email ?? auth.data.user?.email ?? "";

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <div className="app-header__inner">
          <Brand link />
          <nav className="app-nav" aria-label="Main" id="main-menu" data-open={menuOpen}>
            <ul>
              <li>
                <NavLink to="/" end>
                  Your interviews
                </NavLink>
              </li>
              <li>
                <NavLink to="/jobs/new">Add a job</NavLink>
              </li>
              <li>
                <NavLink to="/reports">Reports</NavLink>
              </li>
              <li>
                <NavLink to="/account">Account</NavLink>
              </li>
              {auth.data.user?.is_admin && (
                <li>
                  <NavLink to="/admin">Admin</NavLink>
                </li>
              )}
              {import.meta.env.DEV && (
                <li>
                  <NavLink to="/dev/interview">Text interview (dev)</NavLink>
                </li>
              )}
            </ul>
          </nav>
          <div className="app-header__end">
            <ModelUsageBadge usage={modelUsage.data} />
            {usage.data && <UsageMeter usage={usage.data} />}
            <button
              type="button"
              className="menu-toggle"
              aria-expanded={menuOpen}
              aria-controls="main-menu"
              onClick={() => setMenuOpen((o) => !o)}
            >
              Menu
            </button>
            <AccountMenu email={email} onSignOut={() => logout.mutate()} busy={logout.isPending} />
          </div>
        </div>
      </header>
      <main id="main" className="page">
        <Outlet />
      </main>
    </>
  );
}

/** Shell for the sign-in and sign-up pages: the same stage header, no menu. */
export function PublicLayout() {
  return (
    <>
      <header className="app-header">
        <div className="app-header__inner">
          <Brand link={false} />
        </div>
      </header>
      <main id="main" className="page page--narrow">
        <Outlet />
      </main>
    </>
  );
}
