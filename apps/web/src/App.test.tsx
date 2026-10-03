import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  );
}

describe("App", () => {
  it("shows OK when the API is healthy", async () => {
    stubFetch(200, {
      status: "ok",
      version: "0.1.0",
      model_profile: "fake",
      checks: { database: "ok", redis: "ok" },
    });
    render(<App />);
    expect(await screen.findByTestId("api-status")).toHaveTextContent("OK");
    expect(fetch).toHaveBeenCalledWith("/api/health", expect.anything());
  });

  it("shows DEGRADED when a dependency is down", async () => {
    stubFetch(503, {
      status: "degraded",
      version: "0.1.0",
      model_profile: "fake",
      checks: { database: "ok", redis: "error: ConnectionError" },
    });
    render(<App />);
    expect(await screen.findByTestId("api-status")).toHaveTextContent("DEGRADED");
    expect(screen.getByText("redis: error: ConnectionError")).toBeInTheDocument();
  });

  it("shows an error when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("network down");
  });
});
