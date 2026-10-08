import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { ApiError } from "./api/client";
import { AppLayout, PublicLayout } from "./components/Layout";
import { AccountPage } from "./pages/AccountPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DebriefPage } from "./pages/DebriefPage";
import { GapAnalysisPage } from "./pages/GapAnalysisPage";
import { ConfirmJobPage } from "./pages/onboarding/ConfirmJobPage";
import { ContextPage } from "./pages/onboarding/ContextPage";
import { NewJobPage } from "./pages/onboarding/NewJobPage";
import { ResumePage } from "./pages/onboarding/ResumePage";
import { PaywallPage } from "./pages/PaywallPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SessionSetupPage } from "./pages/SessionSetupPage";
import { SignInPage } from "./pages/SignInPage";
import { SignupPage } from "./pages/SignupPage";
import { LiveSessionPage } from "./session/LiveSessionPage";

// Dev builds only: a text interview against the real API (P7). Production builds drop it.
const DevTextInterviewPage = import.meta.env.DEV
  ? lazy(() => import("./dev/DevTextInterviewPage").then((m) => ({ default: m.DevTextInterviewPage })))
  : null;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Do not retry client errors (404, 401, 402); they will not change on retry.
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/signin" element={<SignInPage />} />
        <Route path="/signup" element={<SignupPage />} />
      </Route>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="/jobs/new" element={<NewJobPage />} />
        <Route path="/jobs/:jobId/confirm" element={<ConfirmJobPage />} />
        <Route path="/jobs/:jobId/resume" element={<ResumePage />} />
        <Route path="/jobs/:jobId/context" element={<ContextPage />} />
        <Route path="/jobs/:jobId/gap" element={<GapAnalysisPage />} />
        <Route path="/jobs/:jobId/sessions/new" element={<SessionSetupPage />} />
        <Route path="/sessions/:sessionId/live" element={<LiveSessionPage />} />
        <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/upgrade" element={<PaywallPage />} />
        {DevTextInterviewPage && (
          <Route
            path="/dev/interview"
            element={
              <Suspense fallback={null}>
                <DevTextInterviewPage />
              </Suspense>
            }
          />
        )}
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
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
