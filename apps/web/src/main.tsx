import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

async function start() {
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
