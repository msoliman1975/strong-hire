/**
 * RSD-13: the compact career strip under steps 2 to 4. Roles are segments sized by months, oldest
 * on the left; gaps over 3 months are hatched in the warn colours; the roles of the current finding
 * are outlined. It is one image with a spoken summary, and "Open and edit" goes to step 1.
 */
import type { CvRole } from "./draft";

const monthIndex = (value: string): number | null => {
  const m = /^(\d{4})(?:-(\d{2}))?$/.exec(value.trim());
  return m ? Number(m[1]) * 12 + (m[2] ? Number(m[2]) - 1 : 0) : null;
};
const year = (index: number) => Math.floor(index / 12);

interface Segment {
  kind: "role" | "gap";
  from: number;
  to: number;
  label: string;
  /** The role's index in the newest-first list. */
  role?: number;
}

/** The segments, oldest first. A role with no start date is left out; no end means now. */
export function careerSegments(roles: CvRole[], today: string): { segments: Segment[]; from: number; to: number } | null {
  const now = monthIndex(today) ?? 0;
  const dated = roles
    .map((r, role) => {
      const from = monthIndex(r.start);
      const to = r.end.trim() ? monthIndex(r.end) : now;
      return from === null || to === null || to < from ? null : { from, to, role, label: r.company.trim() || r.title.trim() || "Role" };
    })
    .filter((s): s is NonNullable<typeof s> => s !== null)
    .sort((a, b) => a.from - b.from || a.to - b.to);
  if (dated.length === 0) return null;
  const segments: Segment[] = [];
  let reach = dated[0].from;
  for (const s of dated) {
    if (s.from - reach > 3) segments.push({ kind: "gap", from: reach, to: s.from, label: "gap" });
    segments.push({ kind: "role", from: s.from, to: s.to, label: s.label, role: s.role });
    reach = Math.max(reach, s.to);
  }
  return { segments, from: dated[0].from, to: Math.max(...dated.map((s) => s.to)) };
}

/** "Timeline: Studio Nine 2014 to 2015, gap, Kitepath 2015 to 2017, Ledgerline 2021 to now". */
export function stripSummary(segments: Segment[], now: number): string {
  const parts = segments.map((s) =>
    s.kind === "gap" ? "gap" : `${s.label} ${year(s.from)} to ${s.to >= now ? "now" : year(s.to)}`,
  );
  return `Timeline: ${parts.join(", ")}`;
}

export function CareerStrip({
  roles,
  today,
  outlined,
  onOpen,
}: {
  roles: CvRole[];
  today: string;
  /** Role indexes (newest-first) of the current finding. */
  outlined: readonly number[];
  onOpen: () => void;
}) {
  const built = careerSegments(roles, today);
  const now = monthIndex(today) ?? 0;
  return (
    <section className="cvc-card cvc-strip" aria-label="Career journey at a glance">
      <div className="cvc-card__head">
        <span className="cvc-label">Your career journey</span>
        <button type="button" className="cvc-link" onClick={onOpen}>
          Open and edit
        </button>
      </div>
      {built ? (
        <>
          <div className="cvc-strip__bar" role="img" aria-label={stripSummary(built.segments, now)}>
            {built.segments.map((s, n) => {
              const total = Math.max(1, built.to - built.from);
              const left = ((s.from - built.from) / total) * 100;
              const width = Math.max(((s.to - s.from) / total) * 100, 1.5);
              const lit = s.role !== undefined && outlined.includes(s.role);
              return (
                <span
                  key={n}
                  className={`cvc-strip__seg cvc-strip__seg--${s.kind}`}
                  data-outlined={lit || undefined}
                  style={{ left: `${left}%`, width: `${width}%` }}
                >
                  {s.kind === "role" && width > 12 ? s.label : null}
                </span>
              );
            })}
          </div>
          <div className="cvc-strip__axis" aria-hidden="true">
            <span>{year(built.from)}</span>
            <span>{built.to >= now ? "now" : year(built.to)}</span>
          </div>
        </>
      ) : (
        <p className="muted">Add dates to your roles to see your career journey.</p>
      )}
    </section>
  );
}
