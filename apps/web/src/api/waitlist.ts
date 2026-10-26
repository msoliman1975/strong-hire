/**
 * The public waitlist (L04 step 1). No account needed. Joining always answers "check_email",
 * whether or not the address was on the list; the emailed link confirms it (double opt-in).
 */
import { apiClient, unwrap } from "./client";
import type { components } from "./schema.gen";

export type WaitlistIn = components["schemas"]["WaitlistIn"];
export type InterviewWithin = components["schemas"]["InterviewWithin"];

export const waitlistApi = {
  join: async (body: WaitlistIn) => unwrap(await apiClient.POST("/public/waitlist", { body })),
  confirm: async (token: string) =>
    unwrap(await apiClient.POST("/public/waitlist/confirm", { body: { token } })),
};
