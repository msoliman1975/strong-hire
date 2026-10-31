import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useMatch, useNavigate } from "react-router";

import { authApi } from "../api/auth";
import { useAuth, useModelUsage, useUsage } from "../api/hooks";
import type { AuthUser, ModelUsage, Usage } from "../api/types";
import { hasSlogan, SLOGAN } from "../labels";
import { useFeature } from "../theme/features";
import { BrandMark } from "./BrandMark";
import { avatarEnabled } from "../session/InterviewerState";
import { ModelUsageBadge } from "./ModelUsageBadge";
import { useFirstRunRedirect } from "../pages/start/gate";
import { isStartPath, startStep } from "../pages/start/paths";
import { StartSteps } from "../pages/start/StartSteps";
import { AvatarMenu, PlanChip } from "./TopBar";
import { Tour } from "./Tour";
import { ErrorNotice, Loading } from "./ui";
import { UsageMeter } from "./UsageMeter";

/** Logo, name and (once agreed) the slogan. A link on signed-in pages, plain text elsewhere. */
function Brand({ link, tone = "light", lockup = false }: { link: boolean; tone?: "light" | "dark"; lockup?: boolean }) {
  const inner = (
    <>
      <BrandMark size={26} tone={tone} />
      <span className="brand__name">Strong Hire</span>
      {/* SV-7: the lockup (ux-spec section 4.5). Strova is never a logo, only these words. */}
      {lockup && <span className="brand__with">with Strova</span>}
      {hasSlogan(SLOGAN) && <span className="brand__slogan">{SLOGAN}</span>}
    </>
  );
  return link ? (
    <Link className="brand" to="/" aria-label={lockup ? "Strong Hire with Strova, home" : "Strong Hire, interview rehearsals"}>
      {inner}
    </Link>
  ) : (
    <span className="brand">{inner}</span>
  );
}

/**
 * Initials button that opens a small menu with the account page and sign out. In v2 it also holds
 * the pages that left the rail: Questions, Resumes and, in dev builds, the text interview.
 */
function AccountMenu({
  email,
  onSignOut,
  busy,
  links = [ACCOUNT_LINK],
}: {
  email: string;
  onSignOut: () => void;
  busy: boolean;
  links?: NavItem[];
}) {
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
        <span className="account-menu__initials" aria-hidden="true">
          {initials}
        </span>
        <span className="account-menu__email-short">{email}</span>
      </button>
      {open && (
        <ul className="account-menu__list">
          {email && <li className="account-menu__email">{email}</li>}
          {links.map((it) => (
            <li key={it.to}>
              <Link to={it.to} onClick={() => setOpen(false)}>
                {it.label}
              </Link>
            </li>
          ))}
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

type NavItem = {
  to: string;
  label: string;
  end?: boolean;
  match?: RegExp;
  badge?: string;
  /** The tour step that points at this item. */
  tour?: string;
};

/** The v1 menu, shown until launch: the same labels and targets, so v1 users find their pages. */
const V1_NAV: NavItem[] = [
  { to: "/", label: "Interview rehearsals", end: true },
  { to: "/jobs", label: "Job descriptions", end: true },
  { to: "/resumes", label: "Resumes" },
  { to: "/reports", label: "Reports" },
  { to: "/questions", label: "Questions" },
  { to: "/account", label: "Account" },
];

/** NV-1: "{First name}'s Resumes" from the profile's full name; "Your resumes" without one. */
export function resumesLabel(fullName: string | null | undefined): string {
  const first = fullName?.trim().split(/\s+/)[0];
  return first ? `${first}'s Resumes` : "Your resumes";
}

/**
 * NV-1: the v2 rail (ux-spec section 5): exactly Home, {First name}'s Resumes, Target roles,
 * Rehearsals with Strova and Career Stories with Strova. NV-3: Question bank and Progress left
 * the rail; their routes still work. Account, Plan and billing, Reports and Sign out are in the
 * top bar's avatar menu.
 */
function v2Nav(fullName: string | null | undefined): NavItem[] {
  return [
    { to: "/", label: "Home", end: true },
    { to: "/resumes", label: resumesLabel(fullName), match: /^\/resumes(\/|$)/ },
    { to: "/roles", label: "Target roles", match: /^\/(roles|jobs)(\/|$)/ },
    { to: "/rehearsals", label: "Rehearsals with Strova", match: /^\/(rehearsals|interviews|sessions)(\/|$)/ },
    { to: "/stories", label: "Career Stories with Strova", match: /^\/(stories|coach)(\/|$)/, tour: "coach" },
  ];
}

const ACCOUNT_LINK: NavItem = { to: "/account", label: "Account" };

const DEV_NAV: NavItem = { to: "/dev/interview", label: "Text interview (dev)" };

/** The v2 avatar menu after Account, Plan and billing and Reports. The dev text interview shows in dev builds only. */
const V2_AVATAR_EXTRA = [{ to: "/help", label: "Help and how it works" }, ...(import.meta.env.DEV ? [DEV_NAV] : [])];

/** UI-2, NV-1: the left rail menu. The v2 items show only when `v2_enabled` is on. */
export function RailNav() {
  const v2 = useFeature("v2_enabled");
  const auth = useAuth();
  const { pathname } = useLocation();
  const item = (it: NavItem) => {
    // NavLink only marks exact routes; items with `match` cover several route trees.
    const matched = it.match?.test(pathname) ?? false;
    const label = (
      <>
        {it.label}
        {it.badge && <span className="rail-nav__badge">{it.badge}</span>}
      </>
    );
    return (
      <li key={it.to} data-tour={it.tour}>
        {matched ? (
          <Link to={it.to} aria-current="page">
            {label}
          </Link>
        ) : (
          <NavLink to={it.to} end={it.end}>
            {label}
          </NavLink>
        )}
      </li>
    );
  };
  return (
    <nav className="rail-nav" aria-label="Main">
      <ul>
        {(v2 ? v2Nav(auth.data?.user?.full_name) : V1_NAV).map(item)}
        {!v2 && import.meta.env.DEV && item(DEV_NAV)}
      </ul>
    </nav>
  );
}

/** Shell for signed-in pages: the left rail (menu, usage meter, account menu) beside the page. */
export function AppLayout() {
  const auth = useAuth();
  const location = useLocation();
  const live = useMatch("/sessions/:sessionId/live") !== null;
  const signedIn = auth.data?.status === "signed_in";
  const usage = useUsage(signedIn);
  const modelUsage = useModelUsage(signedIn);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const v2 = useFeature("v2_enabled");
  // U05: first-run routing (no resume: /start; no plan style: the plan style screen).
  const firstRun = useFirstRunRedirect(v2 && signedIn && Boolean(auth.data?.user?.profile_complete), location.pathname);
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

  // AC-3: the first sign-in asks for the profile before anything else. The menu waits until it is saved.
  const welcome = location.pathname === "/welcome";
  if (auth.data.user && !auth.data.user.profile_complete && !welcome) {
    return <Navigate to="/welcome" replace state={{ from: location.pathname }} />;
  }
  const step = startStep(location.pathname);
  if (v2 && (welcome || isStartPath(location.pathname))) {
    // U05 (ux-spec section 6.1): setup has no rail, only the lockup and the three steps.
    return (
      <>
        <header className="sx-top">
          <Brand link={false} lockup />
          {step && <StartSteps step={step} />}
        </header>
        <main id="main">
          <Outlet />
        </main>
      </>
    );
  }
  if (welcome) {
    return (
      <>
        <header className="app-header">
          <div className="app-header__inner">
            <Brand link={false} lockup={v2} />
            <button type="button" className="header-signout" onClick={() => logout.mutate()}>
              Sign out
            </button>
          </div>
        </header>
        <main id="main" className="page">
          <Outlet />
        </main>
      </>
    );
  }

  // During a live interview the menu is hidden, so nothing pulls the candidate away from the session.
  if (live) {
    // SV-6 (mockup #live): the v2 room is full bleed; its own header shows the take, the
    // connection and the clock, so the slim app header is left out. The 3D avatar build keeps it.
    if (v2 && !avatarEnabled()) {
      return (
        <div className="room room--bleed">
          <main id="main" className="page page--room">
            <Outlet />
          </main>
        </div>
      );
    }
    return (
      <div className="room">
        <header className="app-header app-header--room">
          <div className="app-header__inner">
            <Brand link={false} tone="dark" lockup={v2} />
            <span className="live-bar__status">
              <span className="live-dot" aria-hidden="true" />
              Live interview
            </span>
          </div>
        </header>
        <main id="main" className="page page--room">
          <Outlet />
        </main>
      </div>
    );
  }

  const email = auth.data.email ?? auth.data.user?.email ?? "";

  if (v2 && firstRun === undefined) return <Loading label="Loading your resumes" />;
  if (v2 && firstRun) return <Navigate to={firstRun} replace />;

  if (v2) {
    return (
      <V2Shell
        user={auth.data.user ?? null}
        email={email}
        usage={usage.data}
        modelUsage={modelUsage.data}
        onSignOut={() => logout.mutate()}
        signingOut={logout.isPending}
      />
    );
  }

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="rail">
        <div className="rail__top">
          <Brand link />
          <button
            type="button"
            className="menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="main-menu"
            onClick={() => setMenuOpen((o) => !o)}
          >
            Menu
          </button>
        </div>
        <div className="rail__body" id="main-menu" data-open={menuOpen}>
          <RailNav />
          <div className="rail__foot">
            <ModelUsageBadge usage={modelUsage.data} />
            {usage.data && <UsageMeter usage={usage.data} />}
            <AccountMenu email={email} onSignOut={() => logout.mutate()} busy={logout.isPending} />
          </div>
        </div>
      </aside>
      <main id="main" className="page shell__main">
        <Outlet />
      </main>
    </div>
  );
}

/**
 * The v2 shell (ux-spec section 5): the top bar (the lockup, the usage pill, the initials button
 * for Profile and the account links) and beside the page the rail. On phones the rail becomes a
 * horizontal strip that scrolls.
 */
function V2Shell({
  user,
  email,
  usage,
  modelUsage,
  onSignOut,
  signingOut,
}: {
  user: AuthUser | null;
  email: string;
  usage: Usage | undefined;
  modelUsage: ModelUsage | undefined;
  onSignOut: () => void;
  signingOut: boolean;
}) {
  return (
    <div className="shell2">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar" aria-label="Top bar">
        <Brand link lockup />
        <div className="topbar__right" data-tour="topbar">
          <ModelUsageBadge usage={modelUsage} />
          {usage && <PlanChip usage={usage} />}
          <AvatarMenu
            name={user?.full_name ?? null}
            email={email}
            onSignOut={onSignOut}
            busy={signingOut}
            extraLinks={V2_AVATAR_EXTRA}
          />
        </div>
      </header>
      <div className="shell2__body">
        <aside className="rail rail--v2">
          <div className="rail__body" id="main-menu" data-tour="menu">
            <RailNav />
          </div>
        </aside>
        <main id="main" className="page shell__main">
          <Outlet />
        </main>
      </div>
      {user && <Tour userId={user.id} />}
    </div>
  );
}

/** Shell for the sign-in and sign-up pages: a slim header with the mark, no menu. */
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
