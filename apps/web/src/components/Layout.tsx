import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useMatch, useNavigate } from "react-router";

import { authApi } from "../api/auth";
import { useAuth, useModelUsage, useUsage } from "../api/hooks";
import type { AuthUser, ModelUsage, Usage } from "../api/types";
import { hasSlogan, SLOGAN } from "../labels";
import { newCoachPath } from "../pages/coach/paths";
import { useFeature } from "../theme/features";
import { BrandMark } from "./BrandMark";
import { ModelUsageBadge } from "./ModelUsageBadge";
import { AvatarMenu, PlanChip, UpdatesBell, useFirstVisitGreeting } from "./TopBar";
import { Tour } from "./Tour";
import { CoachMark, ErrorNotice, Loading } from "./ui";
import { UsageMeter } from "./UsageMeter";

/** Logo, name and (once agreed) the slogan. A link on signed-in pages, plain text elsewhere. */
function Brand({ link, tone = "light" }: { link: boolean; tone?: "light" | "dark" }) {
  const inner = (
    <>
      <BrandMark size={26} tone={tone} />
      <span className="brand__name">Strong Hire</span>
      {hasSlogan(SLOGAN) && <span className="brand__slogan">{SLOGAN}</span>}
    </>
  );
  return link ? (
    <Link className="brand" to="/" aria-label="Strong Hire, interview rehearsals">
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

type NavItem = { to: string; label: string; end?: boolean; match?: RegExp; badge?: string };

/** The v1 menu, shown until launch: the same labels and targets, so v1 users find their pages. */
const V1_NAV: NavItem[] = [
  { to: "/", label: "Interview rehearsals", end: true },
  { to: "/jobs", label: "Job descriptions", end: true },
  { to: "/resumes", label: "Resumes" },
  { to: "/reports", label: "Reports" },
  { to: "/questions", label: "Questions" },
  { to: "/account", label: "Account" },
];

/**
 * UI-2: the v2 rail (canvas board R3 Shell): Home, Resumes, Interviews, Stories, Question bank
 * (the Questions page, with My questions as a tab) and Progress (the reports). Account, Plan and
 * billing, Reports and Sign out are in the top bar's avatar menu.
 */
const V2_NAV: NavItem[] = [
  { to: "/", label: "Home", end: true },
  { to: "/resumes", label: "Resumes" },
  { to: "/jobs", label: "Interviews", match: /^\/(jobs|interviews|sessions)(\/|$)/ },
  { to: "/stories", label: "Stories", match: /^\/(stories|coach)(\/|$)/ },
  { to: "/questions", label: "Question bank", match: /^\/questions(\/|$)/, badge: "New" },
  { to: "/reports", label: "Progress" },
];

const ACCOUNT_LINK: NavItem = { to: "/account", label: "Account" };

const DEV_NAV: NavItem = { to: "/dev/interview", label: "Text interview (dev)" };

/** The v2 avatar menu after Account, Plan and billing and Reports. The dev text interview shows in dev builds only. */
const V2_AVATAR_EXTRA = [{ to: "/help", label: "Help and how it works" }, ...(import.meta.env.DEV ? [DEV_NAV] : [])];

/** UI-2: the left rail menu. "Stories" and the v2 labels show only when `v2_enabled` is on. */
export function RailNav() {
  const v2 = useFeature("v2_enabled");
  const { pathname } = useLocation();
  const item = (it: NavItem) => {
    // NavLink only marks exact routes; items with `match` cover several route trees.
    const matched = it.match?.test(pathname) ?? false;
    const label = it.badge ? (
      <>
        {it.label}
        <span className="rail-nav__badge">{it.badge}</span>
      </>
    ) : (
      it.label
    );
    return (
      <li key={it.to}>
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
        {(v2 ? V2_NAV : V1_NAV).map(item)}
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
  if (welcome) {
    return (
      <>
        <header className="app-header">
          <div className="app-header__inner">
            <Brand link={false} />
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
    return (
      <div className="room">
        <header className="app-header app-header--room">
          <div className="app-header__inner">
            <Brand link={false} tone="dark" />
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

  if (v2) {
    return (
      <V2Shell
        user={auth.data.user ?? null}
        email={email}
        usage={usage.data}
        modelUsage={modelUsage.data}
        menuOpen={menuOpen}
        onMenu={() => setMenuOpen((o) => !o)}
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
 * The v2 shell (canvas board R3 Shell): the top bar across the page (the mark, the first-visit
 * greeting, the updates bell, the plan chip, the avatar menu), and beside the page the rail with
 * only the menu and "Talk to your coach". Below 900px the rail folds behind the Menu button.
 */
function V2Shell({
  user,
  email,
  usage,
  modelUsage,
  menuOpen,
  onMenu,
  onSignOut,
  signingOut,
}: {
  user: AuthUser | null;
  email: string;
  usage: Usage | undefined;
  modelUsage: ModelUsage | undefined;
  menuOpen: boolean;
  onMenu: () => void;
  onSignOut: () => void;
  signingOut: boolean;
}) {
  const greeting = useFirstVisitGreeting(user);
  return (
    <div className="shell2">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar" aria-label="Top bar">
        <Brand link />
        {greeting && <p className="topbar__greet">{greeting}</p>}
        <div className="topbar__right" data-tour="topbar">
          <ModelUsageBadge usage={modelUsage} />
          {usage && <PlanChip usage={usage} />}
          {user && <UpdatesBell userId={user.id} />}
          <AvatarMenu
            name={user?.full_name ?? null}
            email={email}
            onSignOut={onSignOut}
            busy={signingOut}
            extraLinks={V2_AVATAR_EXTRA}
          />
          <button
            type="button"
            className="menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="main-menu"
            onClick={onMenu}
            data-tour="menu"
          >
            Menu
          </button>
        </div>
      </header>
      <div className="shell2__body">
        <aside className="rail rail--v2">
          <div className="rail__body" id="main-menu" data-open={menuOpen}>
            <div data-tour="menu">
              <RailNav />
            </div>
            <div className="rail__foot">
              <Link className="rail__coach" to={newCoachPath()} data-tour="coach">
                <CoachMark size={20} tone="dark" />
                Talk to your coach
              </Link>
              {/* Phones: the top bar has no room for the plan chip, so it sits in the menu. */}
              {usage && (
                <div className="rail__plan">
                  <PlanChip usage={usage} />
                </div>
              )}
            </div>
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
