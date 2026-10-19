import type { DiffChange, ProfileDiff } from "../api/content";

export type DiffMode = "side" | "inline";

function show(value: unknown): string {
  if (value === undefined || value === null) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

const SIGN: Record<DiffChange["kind"], string> = { added: "+", removed: "-", changed: "~" };

/**
 * AT-2: the field diff of two profile versions (profiles/diff.py on the API). One block per
 * changed top-level field, side by side (old and new columns) or inline (one line per change).
 */
export function DiffView({ diff, mode }: { diff: ProfileDiff; mode: DiffMode }) {
  const changed = diff.fields.filter((f) => f.changes.length > 0);
  const unchanged = diff.fields.filter((f) => f.changes.length === 0).map((f) => f.field);
  const oldLabel = diff.a === null ? "No version" : `Version ${diff.a}`;
  const newLabel = `Version ${diff.b}`;

  return (
    <div className="diff" aria-label={`Changes from ${oldLabel} to ${newLabel}`}>
      <p>
        {diff.total === 0
          ? "No changes (meta is not compared)."
          : `${diff.total} changed value${diff.total === 1 ? "" : "s"} in ${changed.length} field${
              changed.length === 1 ? "" : "s"
            }.`}
      </p>
      {changed.map((field) => (
        <section key={field.field} className="diff__field">
          <h3>
            {field.field}{" "}
            <span className="muted">
              ({field.changes.length} change{field.changes.length === 1 ? "" : "s"})
            </span>
          </h3>
          {mode === "side" ? (
            <div className="table-wrap">
              <table className="diff__table">
                <thead>
                  <tr>
                    <th scope="col">Path</th>
                    <th scope="col">{oldLabel}</th>
                    <th scope="col">{newLabel}</th>
                  </tr>
                </thead>
                <tbody>
                  {field.changes.map((c) => (
                    <tr key={c.path} data-kind={c.kind}>
                      <td>
                        <code>{c.path}</code>
                      </td>
                      <td className="diff__old">{show(c.old)}</td>
                      <td className="diff__new">{show(c.new)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <ul className="diff__inline">
              {field.changes.map((c) => (
                <li key={c.path} data-kind={c.kind}>
                  <span className="diff__sign" aria-label={c.kind}>
                    {SIGN[c.kind]}
                  </span>{" "}
                  <code>{c.path}</code>:{" "}
                  {c.kind === "changed" ? (
                    <>
                      <del className="diff__old">{show(c.old)}</del> <span aria-hidden="true">→</span>{" "}
                      <ins className="diff__new">{show(c.new)}</ins>
                    </>
                  ) : c.kind === "added" ? (
                    <ins className="diff__new">{show(c.new)}</ins>
                  ) : (
                    <del className="diff__old">{show(c.old)}</del>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
      {unchanged.length > 0 && <p className="muted">Unchanged: {unchanged.join(", ")}</p>}
    </div>
  );
}
