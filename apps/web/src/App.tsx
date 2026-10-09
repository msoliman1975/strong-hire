import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { ApiError } from "./api/client";
import { AppLayout, PublicLayout } from "./components/Layout";
import { AccountPage } from "./pages/AccountPage";
import { AdminAuditPage } from "./pages/admin/AdminAuditPage";
import { AdminLayout } from "./pages/admin/AdminLayout";
import { AdminSessionPage } from "./pages/admin/AdminSessionPage";
import { AdminSessionsPage } from "./pages/admin/AdminSessionsPage";
import { AdminUsersPage } from "./pages/admin/AdminUsersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DebriefPage } from "./pages/DebriefPage";
import { GapAnalysisPage } from "./pages/GapAnalysisPage";
import { JobsPage } from "./pages/JobsPage";
import { ConfirmJobPage } from "./pages/onboarding/ConfirmJobPage";
import { ContextPage } from "./pages/onboarding/ContextPage";
import { NewJobPage } from "./pages/onboarding/NewJobPage";
import { CheckResumePage } from "./pages/onboarding/CheckResumePage";
import { ResumePage } from "./pages/onboarding/ResumePage";
import { PaywallPage } from "./pages/PaywallPage";
import { EditProfilePage, WelcomePage } from "./pages/ProfilePage";
import { RehearsalPage } from "./pages/RehearsalPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ResumesPage } from "./pages/ResumesPage";
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
        <Route path="/welcome" element={<WelcomePage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/resumes" element={<ResumesPage />} />
        <Route path="/resumes/:resumeId/check" element={<CheckResumePage />} />
        <Route path="/jobs/new" element={<NewJobPage />} />
        <Route path="/jobs/:jobId/confirm" element={<ConfirmJobPage />} />
        <Route path="/jobs/:jobId/resume" element={<ResumePage />} />
        <Route path="/jobs/:jobId/resume/:resumeId/check" element={<CheckResumePage />} />
        <Route path="/jobs/:jobId/rehearse/:resumeId" element={<RehearsalPage />} />
        <Route path="/jobs/:jobId/context" element={<ContextPage />} />
        <Route path="/jobs/:jobId/gap" element={<GapAnalysisPage />} />
        <Route path="/jobs/:jobId/sessions/new" element={<SessionSetupPage />} />
        <Route path="/sessions/:sessionId/live" element={<LiveSessionPage />} />
        <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/account/profile" element={<EditProfilePage />} />
        <Route path="/upgrade" element={<PaywallPage />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="interviews" replace />} />
          <Route path="interviews" element={<AdminSessionsPage />} />
          <Route path="interviews/:sessionId" element={<AdminSessionPage />} />
          <Route path="users" element={<AdminUsersPage />} />
          <Route path="audit" element={<AdminAuditPage />} />
        </Route>
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
