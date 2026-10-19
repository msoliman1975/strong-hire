import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { ApiError } from "./api/client";
import { Shell } from "./components/Shell";
import { AdminAuditPage } from "./pages/AdminAuditPage";
import { AlertHistoryPage } from "./pages/AlertHistoryPage";
import { AlertRuleEditPage } from "./pages/AlertRuleEditPage";
import { AlertRulesPage } from "./pages/AlertRulesPage";
import { AdminSessionPage } from "./pages/AdminSessionPage";
import { AdminSessionsPage } from "./pages/AdminSessionsPage";
import { AdminUserPage } from "./pages/AdminUserPage";
import { AdminsPage } from "./pages/AdminsPage";
import { AdminUsersPage } from "./pages/AdminUsersPage";
import { MySessionsPage } from "./pages/MySessionsPage";
import { ControlsPage } from "./pages/ControlsPage";
import { OpsErrorsPage, OpsHealthPage, OpsJobsPage, OpsPerformancePage, OpsSpendPage } from "./pages/OpsPages";
import { OverviewPage } from "./pages/OverviewPage";
import { CompaniesPage } from "./pages/CompaniesPage";
import { CompanyPage } from "./pages/CompanyPage";
import { CompanyRequestsPage } from "./pages/CompanyRequestsPage";
import { SignInPage } from "./pages/SignInPage";
import { VerifyLinkPage } from "./pages/VerifyLinkPage";

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
      <Route path="/signin/verify" element={<VerifyLinkPage />} />
      <Route element={<Shell />}>
        <Route index element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/interviews" element={<AdminSessionsPage />} />
        <Route path="/interviews/:sessionId" element={<AdminSessionPage />} />
        <Route path="/users" element={<AdminUsersPage />} />
        <Route path="/users/:userId" element={<AdminUserPage />} />
        <Route path="/audit" element={<AdminAuditPage />} />
        <Route path="/ops/controls" element={<ControlsPage />} />
        <Route path="/alerts" element={<Navigate to="/alerts/rules" replace />} />
        <Route path="/alerts/rules" element={<AlertRulesPage />} />
        <Route path="/alerts/rules/:ruleId" element={<AlertRuleEditPage />} />
        <Route path="/alerts/history" element={<AlertHistoryPage />} />
        <Route path="/ops" element={<Navigate to="/ops/health" replace />} />
        <Route path="/ops/health" element={<OpsHealthPage />} />
        <Route path="/ops/performance" element={<OpsPerformancePage />} />
        <Route path="/ops/errors" element={<OpsErrorsPage />} />
        <Route path="/ops/jobs" element={<OpsJobsPage />} />
        <Route path="/ops/spend" element={<OpsSpendPage />} />
        <Route path="/content/companies" element={<CompaniesPage />} />
        <Route path="/content/companies/:slug" element={<CompanyPage />} />
        <Route path="/content/requests" element={<CompanyRequestsPage />} />
        <Route path="/settings" element={<Navigate to="/settings/admins" replace />} />
        <Route path="/settings/admins" element={<AdminsPage />} />
        <Route path="/settings/sessions" element={<MySessionsPage />} />
        <Route path="*" element={<Navigate to="/overview" replace />} />
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
