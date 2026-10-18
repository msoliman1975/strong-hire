import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { ApiError } from "./api/client";
import { Shell } from "./components/Shell";
import { AdminAuditPage } from "./pages/AdminAuditPage";
import { AdminSessionPage } from "./pages/AdminSessionPage";
import { AdminSessionsPage } from "./pages/AdminSessionsPage";
import { AdminUsersPage } from "./pages/AdminUsersPage";
import { ControlsPage } from "./pages/ControlsPage";
import { SignInPage } from "./pages/SignInPage";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Do not retry client errors (404, 401); they will not change on retry.
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
        refetchOnWindowFocus: false,
      },
    },
  });
}

/** Routes follow the Information architecture in docs/admin-spec.md. */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/signin" element={<SignInPage />} />
      <Route element={<Shell />}>
        <Route index element={<Navigate to="/interviews" replace />} />
        <Route path="/interviews" element={<AdminSessionsPage />} />
        <Route path="/interviews/:sessionId" element={<AdminSessionPage />} />
        <Route path="/users" element={<AdminUsersPage />} />
        <Route path="/audit" element={<AdminAuditPage />} />
        <Route path="/ops/controls" element={<ControlsPage />} />
        <Route path="*" element={<Navigate to="/interviews" replace />} />
      </Route>
    </Routes>
  );
}

export function App() {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
