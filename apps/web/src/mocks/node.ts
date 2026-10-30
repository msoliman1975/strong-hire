/** MSW for Vitest. Every request is mocked, with no processing delay. */
import { setupServer } from "msw/node";

import { acceptedIssuesHandlers } from "./acceptedIssuesHandlers";
import { interviewHandlers } from "./interviewHandlers";
import { resumeHandlers } from "./resumeHandlers";
import { coachHandlers } from "./coachHandlers";
import { coachVoiceHandlers } from "./coachVoiceHandlers";
import { customHandlers } from "./custom";
import { createStore } from "./db";
import { accountHandlers, authHandlers, inputHandlers, sessionHandlers, scoringHandlers } from "./handlers";
import { planHandlers } from "./planHandlers";
import { storyFitHandlers } from "./storyFitHandlers";
import { questionHandlers } from "./questionHandlers";
import { readinessHandlers } from "./readinessHandlers";
import { storyHandlers } from "./storyHandlers";
import { transcriptHandlers } from "./transcriptHandlers";
import { waitlistHandlers } from "./waitlistHandlers";

export const mockStore = createStore({ persist: false, delayMs: 0 });
export const server = setupServer(
  ...inputHandlers(mockStore),
  ...acceptedIssuesHandlers(mockStore),
  ...resumeHandlers(mockStore),
  ...interviewHandlers(mockStore),
  ...sessionHandlers(mockStore),
  ...scoringHandlers(mockStore),
  ...authHandlers(mockStore),
  ...accountHandlers(mockStore),
  ...customHandlers(mockStore),
  ...planHandlers(mockStore),
  ...storyFitHandlers(),
  ...readinessHandlers(),
  ...questionHandlers(),
  ...storyHandlers(),
  ...waitlistHandlers(),
  ...coachVoiceHandlers(),
  ...coachHandlers(),
  ...transcriptHandlers(),
);
