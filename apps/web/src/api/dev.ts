/**
 * Dev-only API (testing and validation). GET /dev/model-usage exists only when the API runs with
 * APP_ENV local or test; it reports Claude spend against the LiteLLM budgets.
 */
import { apiClient, unwrap } from "./client";
import type { ModelUsage } from "./types";

export const devApi = {
  modelUsage: async () => unwrap(await apiClient.GET("/dev/model-usage")) as ModelUsage,
};
