/**
 * Dev API (testing and validation). GET /dev/model-usage answers when the API runs with APP_ENV
 * local or test, and in staging for the MODEL_SPEND_VIEWERS emails; it reports Claude spend
 * against the LiteLLM budgets.
 */
import { apiClient, unwrap } from "./client";
import type { ModelUsage } from "./types";

export const devApi = {
  modelUsage: async () => unwrap(await apiClient.GET("/dev/model-usage")) as ModelUsage,
};
