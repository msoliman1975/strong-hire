import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { ApiError } from "./api/client";
import { AuthLayout } from "./components/AuthLayout";
import { AppLayout, PublicLayout } from "./components/Layout";
import { SiteBanner } from "./components/SiteBanner";
import { AccountPage } from "./pages/AccountPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DebriefPage } from "./pages/DebriefPage";
import { GapAnalysisPage } from "./pages/GapAnalysisPage";
import { HelpPage } from "./pages/HelpPage";
import { JobsPage } from "./pages/JobsPage";
import { MyQuestionsPage } from "./pages/MyQuestionsPage";
import { CoachSessionPage } from "./pages/coach/CoachSessionPage";
import { CoachStartPage } from "./pages/coach/CoachStartPage";
import { ConfirmJobPage } from "./pages/onboarding/ConfirmJobPage";
import { ContextPage } from "./pages/onboarding/ContextPage";
import { NewJobPage } from "./pages/onboarding/NewJobPage";
import { CheckResumePage } from "./pages/onboarding/CheckResumePage";
import { ResumePage } from "./pages/onboarding/ResumePage";
import { PaywallPage } from "./pages/PaywallPage";
import { PlanPage } from "./pages/plan/PlanPage";
import { V2Redirect } from "./pages/plan/V2Redirect";
import { EditProfilePage, WelcomePage } from "./pages/ProfilePage";
import { RehearsalPage } from "./pages/RehearsalPage";
import { QuestionsPage } from "./pages/QuestionsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { ResumesPage } from "./pages/ResumesPage";
import { SessionSetupPage } from "./pages/SessionSetupPage";
import { SignInPage } from "./pages/SignInPage";
import { SignupPage } from "./pages/SignupPage";
import { NewStoryPage } from "./pages/stories/NewStoryPage";
import { StoriesPage } from "./pages/stories/StoriesPage";
import { StoryWorkbenchPage } from "./pages/stories/StoryWorkbenchPage";
import { V2Only } from "./pages/stories/V2Only";
import { WaitlistConfirmPage, WaitlistPage } from "./pages/WaitlistPage";
import { TranscriptPage } from "./pages/transcript/TranscriptPage";
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
    <>
      <SiteBanner />
      <Routes>
        <Route element={<AuthLayout />}>
          <Route path="/signin" element={<SignInPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
        </Route>
        <Route element={<PublicLayout />}>
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/waitlist" element={<WaitlistPage />} />
          <Route path="/waitlist/confirm" element={<WaitlistConfirmPage />} />
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
          <Route path="/jobs/:jobId/rehearse/:resumeId" element={<V2Redirect><RehearsalPage /></V2Redirect>} />
          <Route path="/jobs/:jobId/context" element={<ContextPage />} />
          <Route path="/jobs/:jobId/gap" element={<V2Redirect><GapAnalysisPage /></V2Redirect>} />
          <Route path="/jobs/:jobId/sessions/new" element={<V2Redirect><SessionSetupPage /></V2Redirect>} />
          {/* v2 S10: the interview plan page (PP-1). The three routes above open it when v2_enabled is on. */}
          <Route path="/interviews/:jobId/:resumeId" element={<PlanPage />} />
          <Route path="/sessions/:sessionId/live" element={<LiveSessionPage />} />
          <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
          <Route path="/sessions/:sessionId/transcript" element={<TranscriptPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/stories" element={<V2Only><StoriesPage /></V2Only>} />
          <Route path="/stories/new" element={<V2Only><NewStoryPage /></V2Only>} />
          <Route path="/stories/:storyId" element={<V2Only><StoryWorkbenchPage /></V2Only>} />
          {/* v2 S31: coach sessions (CO-2). */}
          <Route path="/coach/new" element={<V2Only><CoachStartPage /></V2Only>} />
          <Route path="/coach/:sessionId" element={<V2Only><CoachSessionPage /></V2Only>} />
          <Route path="/questions" element={<QuestionsPage />} />
          <Route path="/questions/mine" element={<MyQuestionsPage />} />
          <Route path="/account" element={<AccountPage />} />
          {/* R3: How it works, from the v2 avatar menu. */}
          <Route path="/help" element={<HelpPage />} />
          <Route path="/account/profile" element={<EditProfilePage />} />
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
    </>
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
