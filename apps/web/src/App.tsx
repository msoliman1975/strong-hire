import { useEffect, useState } from "react";

import { fetchHealth, type Health } from "./api";

type State = { kind: "loading" } | { kind: "done"; health: Health } | { kind: "error"; message: string };

export function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    fetchHealth(ctrl.signal)
      .then((health) => setState({ kind: "done", health }))
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted) {
          setState({ kind: "error", message: err instanceof Error ? err.message : String(err) });
        }
      });
    return () => ctrl.abort();
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 640, margin: "48px auto", padding: "0 16px" }}>
      <h1>Strong Hire</h1>
      {state.kind === "loading" && <p>Checking the API...</p>}
      {state.kind === "error" && <p role="alert">API unreachable: {state.message}</p>}
      {state.kind === "done" && (
        <section aria-label="API health">
          <p>
            API status: <strong data-testid="api-status">{state.health.status.toUpperCase()}</strong>
          </p>
          <ul>
            {Object.entries(state.health.checks).map(([name, result]) => (
              <li key={name}>
                {name}: {result}
              </li>
            ))}
            <li>model profile: {state.health.model_profile}</li>
            <li>version: {state.health.version}</li>
          </ul>
        </section>
      )}
    </main>
  );
}
