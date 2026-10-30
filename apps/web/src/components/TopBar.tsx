/**
 * The v2 top bar (canvas board R3 Shell): the greeting on the first visit, the updates bell, the
 * plan chip and the avatar menu. It replaces the plan meter and the account menu that sat at the
 * bottom of the rail. The rail keeps only the menu and "Talk to your coach".
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";

import { useReports } from "../api/hooks";
import { reportPath } from "../api/reports";
import { useSiteStatus } from "../api/status";
import type { AuthUser, ReportItem, Usage } from "../api/types";
import { formatDate, interviewTypeLabel } from "../labels";

/** Browser storage is a convenience here: every read and write is guarded, and the bar works without it. */
const store = {
  get(key: string): string | null {
    try {
      return globalThis.localStorage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  },
  set(key: string, value: string) {
    try {
      globalThis.localStorage?.setItem(key, value);
    } catch {
      /* private mode or blocked storage: nothing to remember */
    }
  },
};

const greetedKey = (userId: string) => `sh-greeted-${userId}`;
const seenKey = (userId: string) => `sh-updates-seen-${userId}`;

/** "Welcome, Sara. Let's get you ready." On the first visit only; after that the slot stays empty. */
export function useFirstVisitGreeting(user: AuthUser | null | undefined): string | null {
  const id = user?.id ?? null;
  const [show] = useState(() => id !== null && store.get(greetedKey(id)) === null);
  useEffect(() => {
    if (id && show) store.set(greetedKey(id), new Date().toISOString());
  }, [id, show]);
  if (!show || !user) return null;
  const first = user.full_name?.trim().split(/\s+/)[0];
  return first ? `Welcome, ${first}. Let's get you ready.` : "Welcome. Let's get you ready.";
}

/** The plan and what is left of it, with Upgrade on the free plan. Numbers come from GET /billing/usage. */
export function PlanChip({ usage }: { usage: Usage }) {
  if (usage.plan === "free") {
    const left = Math.max(usage.free_interviews_left, 0);
    return (
      <span className="plan-chip">
        Free plan · {left} mini {left === 1 ? "interview" : "interviews"} left{" "}
        <Link to="/upgrade">Upgrade</Link>
      </span>
    );
  }
  const left = Math.max(usage.minutes_left, 0);
  return (
    <span className="plan-chip" data-testid="plan-chip">
      Monthly plan · {left} of {usage.minutes_cap} minutes left
    </span>
  );
}

export interface UpdateItem {
  id: string;
  title: string;
  detail: string;
  /** ISO time, for the order. */
  at: string;
  to?: string;
}

/** What's new in the app: a small static list, newest first. Add a row when a feature ships. */
export const WHATS_NEW: UpdateItem[] = [
  {
    id: "question-bank",
    title: "New: Question bank",
    detail: "Practice questions, and save your own.",
    at: "2026-10-28T00:00:00Z",
    to: "/questions",
  },
];

const MAX_DEBRIEFS = 3;

function debriefItem(r: ReportItem): UpdateItem {
  const kind = r.interview_type ? `${interviewTypeLabel[r.interview_type]} rehearsal` : "Rehearsal";
  return {
    id: `debrief-${r.id}`,
    title: "Your debrief is ready",
    detail: `${kind}${r.job_name ? ` · ${r.job_name}` : ""} · ${formatDate(r.at)}`,
    at: r.at,
    to: reportPath(r),
  };
}

/** The bell's items: ready debriefs, the site banner while it shows, and what's new. Newest first. */
export function useUpdates(): UpdateItem[] {
  const reports = useReports({ type: "interview_debrief" });
  const status = useSiteStatus();
  const items: UpdateItem[] = (reports.data ?? [])
    .filter((r) => r.status === "ready")
    .slice(0, MAX_DEBRIEFS)
    .map(debriefItem);
  // GET /status sends the banner only while it shows (OC-4); it goes first, as the most urgent.
  const banner = status.data?.banner;
  const head: UpdateItem[] = banner
    ? [{ id: `banner-${banner.until}-${banner.text}`, title: banner.text, detail: "From the Strong Hire team", at: banner.until }]
    : [];
  return [...head, ...[...items, ...WHATS_NEW].sort((a, b) => b.at.localeCompare(a.at))];
}

const readSeen = (userId: string): Set<string> => {
  try {
    return new Set(JSON.parse(store.get(seenKey(userId)) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
};

/** Closes a popover on Escape and on a click outside it. */
function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open, close]);
  return ref;
}

/** The bell, with a dot while it holds something the user has not opened it to see. */
export function UpdatesBell({ userId }: { userId: string }) {
  const items = useUpdates();
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(() => readSeen(userId));
  // The items that were new when the panel opened, so the list can mark them after the dot clears.
  const [fresh, setFresh] = useState<Set<string>>(() => new Set());
  const close = () => setOpen(false);
  const ref = useDismiss(open, close);
  const unread = items.filter((i) => !seen.has(i.id)).length;

  const toggle = () => {
    if (!open) {
      const all = new Set([...seen, ...items.map((i) => i.id)]);
      setFresh(new Set(items.filter((i) => !seen.has(i.id)).map((i) => i.id)));
      setSeen(all);
      store.set(seenKey(userId), JSON.stringify([...all]));
    }
    setOpen((o) => !o);
  };

  return (
    <div className="topbar__pop" ref={ref}>
      <button
        type="button"
        className="topbar__icon"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={unread > 0 ? `Updates, ${unread} new` : "Updates"}
        onClick={toggle}
      >
        <BellIcon />
        {unread > 0 && <span className="topbar__dot" aria-hidden="true" />}
      </button>
      {open && (
        <div className="topbar__menu topbar__updates" role="region" aria-label="Updates">
          <p className="topbar__menu-label">Updates</p>
          {items.length === 0 ? (
            <p className="muted small">Nothing new yet.</p>
          ) : (
            <ul className="plain-list">
              {items.map((i) => (
                <li key={i.id} data-unread={fresh.has(i.id) || undefined}>
                  <UpdateBody item={i} onGo={close} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function UpdateBody({ item, onGo }: { item: UpdateItem; onGo: () => void }) {
  const body: ReactNode = (
    <>
      <b>{item.title}</b>
      <span className="muted small">{item.detail}</span>
    </>
  );
  return item.to ? (
    <Link to={item.to} onClick={onGo}>
      {body}
    </Link>
  ) : (
    <div>{body}</div>
  );
}

const AVATAR_LINKS: { to: string; label: string }[] = [
  // SV-7: the initials button opens Profile first.
  { to: "/account/profile", label: "Profile" },
  { to: "/account", label: "Account" },
  { to: "/account#plan", label: "Plan and billing" },
  { to: "/reports", label: "Reports" },
];

/** Initials that open Profile, Account, Plan and billing, Reports, Help and how it works, and Sign out. */
export function AvatarMenu({
  name,
  email,
  onSignOut,
  busy,
  extraLinks = [],
}: {
  name: string | null;
  email: string;
  onSignOut: () => void;
  busy: boolean;
  /** Pages added after this menu, like "Help and how it works". */
  extraLinks?: { to: string; label: string }[];
}) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const initials = (name?.trim() || email).slice(0, 2).toUpperCase() || "ME";
  return (
    <div className="topbar__pop" ref={ref}>
      <button
        type="button"
        className="topbar__avatar"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Account menu"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="account-menu__initials" aria-hidden="true">
          {initials}
        </span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="topbar__menu topbar__account">
          <p className="topbar__who">
            {name && <b>{name}</b>}
            <span className="muted small">{email}</span>
          </p>
          <ul className="plain-list">
            {[...AVATAR_LINKS, ...extraLinks].map((l) => (
              <li key={l.to}>
                <Link to={l.to} onClick={() => setOpen(false)}>
                  {l.label}
                </Link>
              </li>
            ))}
            <li className="topbar__signout">
              <button type="button" onClick={onSignOut} disabled={busy}>
                Sign out
              </button>
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}

function BellIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}
