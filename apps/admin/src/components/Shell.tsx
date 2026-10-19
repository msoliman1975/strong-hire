import { useState, type ComponentType } from "react";
import { Link, Navigate, NavLink, Outlet } from "react-router";

import { activeControls, useOpsSettings } from "../api/controls";

import { useHealth } from "../api/health";
import { useAuth, useSignOut } from "../api/hooks";
import { FiringCount } from "./alerts";
import { Brand } from "./Brand";
import { applyTheme, savedTheme, systemTheme, type Theme } from "./theme";
import { ErrorNotice, Loading, PageHead } from "./ui";

/**
 * The sections of the admin app (Information architecture in docs/admin-spec.md). Only the ones
 * that exist are listed; later PRs add Content, Alerts and Settings here. Entries with the same
 * `group` are listed together under that heading (for example Operations).
 */
const SECTIONS: { to: string; label: string; group?: string; badge?: ComponentType }[] = [
  { to: "/overview", label: "Overview" },
  { to: "/interviews", label: "Interviews" },
  { to: "/simulations", label: "Simulations" },
  { to: "/users", label: "Users" },
  { to: "/alerts", label: "Alerts", badge: FiringCount },
  { to: "/ops/health", label: "Health", group: "Operations" },
  { to: "/ops/performance", label: "Performance", group: "Operations" },
  { to: "/ops/errors", label: "Errors", group: "Operations" },
  { to: "/ops/jobs", label: "Jobs", group: "Operations" },
  { to: "/ops/spend", label: "Spend", group: "Operations" },
  { to: "/ops/controls", label: "Controls", group: "Operations" },
  { to: "/content/companies", label: "Companies", group: "Content" },
  { to: "/content/requests", label: "Company requests", group: "Content" },
  { to: "/audit", label: "Audit log" },
];

/**
 * OC: a banner on every admin page while any ops control is not at its default, so nobody
 * forgets that sign-ups or sessions are paused.
 */
function ControlsBanner() {
  const settings = useOpsSettings();
  if (!settings.data) return null;
  const active = activeControls(settings.data);
  if (active.length === 0) return null;
  return (
    <div className="ops-banner" role="status">
      <strong>Ops controls on:</strong> {active.join(" · ")}. <Link to="/ops/controls">Open Controls</Link>
    </div>
  );
}

type NavLeaf = { to: string; label: string; badge?: ComponentType };
type NavGroup = { group: string; items: NavLeaf[] };

/** SECTIONS with grouped entries folded under their group, in first-seen order. */
function navItems(): (NavLeaf | NavGroup)[] {
  const out: (NavLeaf | NavGroup)[] = [];
  for (const s of SECTIONS) {
    if (!s.group) {
      out.push({ to: s.to, label: s.label, badge: s.badge });
      continue;
    }
    const found = out.find((n): n is NavGroup => "group" in n && n.group === s.group);
    const leaf = { to: s.to, label: s.label, badge: s.badge };
    if (found) found.items.push(leaf);
    else out.push({ group: s.group, items: [leaf] });
  }
  return out;
}

/** The server's model profile (from /api/health), so admins see which environment this is. */
function EnvLabel() {
  const health = useHealth();
  const profile = health.data?.model_profile;
  if (!profile) return null;
  return (
    <span className="badge badge--env" data-env={profile} title="Model profile on this server">
      {profile}
    </span>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => savedTheme() ?? systemTheme());
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="btn btn--ghost btn--small"
      onClick={() => {
        applyTheme(next);
        setTheme(next);
      }}
    >
      {next === "dark" ? "Dark theme" : "Light theme"}
    </button>
  );
}

function SignOutButton() {
  const signOut = useSignOut();
  return (
    <button
      type="button"
      className="btn btn--small"
      onClick={() => signOut.mutate()}
      disabled={signOut.isPending}
    >
      Sign out
    </button>
  );
}

/**
 * AA-4 on the screen: only admins see the app. Anyone else who is signed in (or a sign-in that
 * would need a candidate sign-up) gets "Page not found" and a way to sign out. The API answers 404
 * to them as well, so this check is for the screen only.
 */
export function Shell() {
  const auth = useAuth();
  if (auth.isPending) return <Loading label="Checking your sign-in" />;
  if (auth.isError) {
    return (
      <main className="centered">
        <ErrorNotice error={auth.error} title="The admin app cannot reach the server." />
      </main>
    );
  }
  const state = auth.data;
  if (state.status === "signed_out") return <Navigate to="/signin" replace />;
  if (!state.user?.is_admin) {
    return (
      <main id="main" className="centered">
        <div className="card">
          <PageHead title="Page not found">
            <p>This page does not exist.</p>
          </PageHead>
          <p className="muted">Signed in as {state.email}.</p>
          <SignOutButton />
        </div>
      </main>
    );
  }

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="sidebar">
        <div className="sidebar__top">
          <Brand />
          <EnvLabel />
        </div>
        <nav className="nav" aria-label="Admin">
          <ul>
            {navItems().map((n) =>
              "group" in n ? (
                <li key={n.group} className="nav__group">
                  <span className="nav__heading" id={`nav-${n.group}`}>
                    {n.group}
                  </span>
                  <ul aria-labelledby={`nav-${n.group}`}>
                    {n.items.map((s) => (
                      <li key={s.to}>
                        <NavLink to={s.to}>
                          {s.label}
                          {s.badge && <s.badge />}
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                </li>
              ) : (
                <li key={n.to}>
                  <NavLink to={n.to}>
                    {n.label}
                    {n.badge && <n.badge />}
                  </NavLink>
                </li>
              ),
            )}
          </ul>
        </nav>
        <div className="sidebar__end">
          <p className="who" title={state.email ?? undefined}>
            {state.email}
          </p>
          <div className="row">
            <SignOutButton />
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main id="main" className="content">
        <ControlsBanner />
        <Outlet />
      </main>
    </div>
  );
}
