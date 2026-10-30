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
import { GapReport } from "./pages/plan/GapReport";
import { RetiredPlanRedirect, V2Redirect } from "./pages/plan/V2Redirect";
import { InterviewPage } from "./pages/rehearsals/InterviewPage";
import { RehearsalsPage } from "./pages/rehearsals/RehearsalsPage";
import { AddRolePage } from "./pages/roles/AddRolePage";
import { RolePage } from "./pages/roles/RolePage";
import { RolesPage } from "./pages/roles/RolesPage";
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
import { ReviewPage } from "./pages/stories/ReviewPage";
import { StoryWorkbenchPage } from "./pages/stories/StoryWorkbenchPage";
import { ResumeDetailPage } from "./pages/resumes/ResumeDetailPage";
import { ResumesListPage } from "./pages/resumes/ResumesListPage";
import { BreakdownPage } from "./pages/start/BreakdownPage";
import { PlanStylePage } from "./pages/start/PlanStylePage";
import { ReadingPage } from "./pages/start/ReadingPage";
import { ResumeReadyPage } from "./pages/start/ResumeReadyPage";
import { StartPage } from "./pages/start/StartPage";
import { WhatFirstPage } from "./pages/start/WhatFirstPage";
import { V2Only } from "./pages/stories/V2Only";
import { useFeature } from "./theme/features";
import { WaitlistConfirmPage, WaitlistPage } from "./pages/WaitlistPage";
import { TranscriptPage } from "./pages/transcript/TranscriptPage";
import { LiveSessionPage } from "./session/LiveSessionPage";

// Dev builds only: a text interview against the real API (P7). Production builds drop it.
const DevTextInterviewPage = import.meta.env.DEV
  ? lazy(() => import("./dev/DevTextInterviewPage").then((m) => ({ default: m.DevTextInterviewPage })))
  : null;
// Dev builds only: the Strova avatar in every mode and size (U02 fidelity check).
const StrovaPreviewPage = import.meta.env.DEV
  ? lazy(() => import("./dev/StrovaPreviewPage").then((m) => ({ default: m.StrovaPreviewPage })))
  : null;

/** RM-1: "{First name}'s Resumes" with v2 on; the v1 Resumes page otherwise. */
/** TG-2: with v2 on, adding a job is adding a target role. */
function AddRoleRoute() {
  return useFeature("v2_enabled") ? <Navigate to="/roles/new" replace /> : <NewJobPage />;
}

function ResumesRoute() {
  return useFeature("v2_enabled") ? <ResumesListPage /> : <ResumesPage />;
}

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
        {StrovaPreviewPage && (
          <Route
            path="/dev/strova"
            element={
              <Suspense fallback={null}>
                <StrovaPreviewPage />
              </Suspense>
            }
          />
        )}
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
          {/* U05: first run with v2 on (ON-1 to ON-6). */}
          <Route path="/start" element={<V2Only><StartPage /></V2Only>} />
          <Route path="/start/reading/:resumeId" element={<V2Only><ReadingPage /></V2Only>} />
          <Route path="/start/ready/:resumeId" element={<V2Only><ResumeReadyPage /></V2Only>} />
          <Route path="/start/check/:resumeId" element={<V2Only><BreakdownPage /></V2Only>} />
          <Route path="/start/plan-style" element={<V2Only><PlanStylePage /></V2Only>} />
          <Route path="/start/what-first" element={<V2Only><WhatFirstPage /></V2Only>} />
          <Route path="/jobs" element={<JobsPage />} />
          {/* NV-1: the v2 rail's routes. Placeholders until U07 builds Target roles and Rehearsals. */}
          {/* U07: target roles, rehearsals and interviews (TG-1, TG-2, TG-4, RH-3, RH-4). */}
          <Route path="/roles" element={<V2Only><RolesPage /></V2Only>} />
          <Route path="/roles/new" element={<V2Only><AddRolePage /></V2Only>} />
          <Route path="/roles/:jobId" element={<V2Only><RolePage /></V2Only>} />
          <Route path="/rehearsals" element={<V2Only><RehearsalsPage /></V2Only>} />
          <Route path="/interviews/:interviewId" element={<V2Only><InterviewPage /></V2Only>} />
          {/* RM-1, RM-3: the v2 resume pages; v1 keeps its Resumes page. */}
          <Route path="/resumes" element={<ResumesRoute />} />
          <Route path="/resumes/:resumeId" element={<V2Only><ResumeDetailPage /></V2Only>} />
          <Route path="/resumes/:resumeId/check" element={<CheckResumePage />} />
          <Route path="/jobs/new" element={<AddRoleRoute />} />
          <Route path="/jobs/:jobId/confirm" element={<ConfirmJobPage />} />
          <Route path="/jobs/:jobId/resume" element={<ResumePage />} />
          <Route path="/jobs/:jobId/resume/:resumeId/check" element={<CheckResumePage />} />
          <Route path="/jobs/:jobId/rehearse/:resumeId" element={<V2Redirect><RehearsalPage /></V2Redirect>} />
          <Route path="/jobs/:jobId/context" element={<ContextPage />} />
          <Route path="/jobs/:jobId/gap" element={<V2Redirect><GapAnalysisPage /></V2Redirect>} />
          {/* The v2 gap report, from the plan ("Show full report") and Interviews ("View gap report"). */}
          <Route path="/jobs/:jobId/gap-report" element={<V2Only><GapReport /></V2Only>} />
          <Route path="/jobs/:jobId/sessions/new" element={<V2Redirect><SessionSetupPage /></V2Redirect>} />
          {/* v2 S10: the interview plan page (PP-1). The three routes above open it when v2_enabled is on. */}
          <Route path="/interviews/:jobId/:resumeId" element={<RetiredPlanRedirect />} />
          <Route path="/sessions/:sessionId/live" element={<LiveSessionPage />} />
          <Route path="/sessions/:sessionId/debrief" element={<DebriefPage />} />
          <Route path="/sessions/:sessionId/transcript" element={<TranscriptPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/stories" element={<V2Only><StoriesPage /></V2Only>} />
          <Route path="/stories/new" element={<V2Only><NewStoryPage /></V2Only>} />
          <Route path="/stories/:storyId" element={<V2Only><StoryWorkbenchPage /></V2Only>} />
          <Route path="/stories/:storyId/review" element={<V2Only><ReviewPage /></V2Only>} />
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
