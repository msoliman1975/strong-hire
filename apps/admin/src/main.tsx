import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { applyTheme, savedTheme } from "./components/theme";

async function start() {
  applyTheme(savedTheme());
  // Mocks exist only in development builds; `import.meta.env.DEV` removes this from production.
  if (import.meta.env.DEV) {
    const { mockMode, startMocks } = await import("./mocks/browser");
    await startMocks(mockMode());
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
