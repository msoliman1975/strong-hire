/**
 * Billing (P9: BL-1, BL-2). These endpoints exist in the API, so they use the typed client.
 * The plan price, the minute cap and the number of free interviews come from the API config.
 */
import { apiClient, unwrap } from "./client";
import type { ExitSurveyIn, PlanOffer, Usage } from "./types";

export const billingApi = {
  usage: async () => unwrap(await apiClient.GET("/billing/usage")) as Usage,
  plan: async () => unwrap(await apiClient.GET("/billing/plan")) as PlanOffer,
  /** Returns the Stripe Checkout URL to send the browser to. */
  checkout: async () => unwrap(await apiClient.POST("/billing/checkout")),
  /** Returns the Stripe Customer Portal URL. "cancel" opens the cancellation step. */
  portal: async (flow: "manage" | "cancel" = "manage") =>
    unwrap(await apiClient.POST("/billing/portal", { body: { flow } })),
  /** The two cancellation questions. */
  exitSurvey: async (body: ExitSurveyIn) => unwrap(await apiClient.POST("/billing/exit-survey", { body })),
};
