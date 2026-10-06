/**
 * Account self-service (P9: AC-1 export and delete, AC-2 consent). Real API endpoints.
 */
import { apiClient, unwrap } from "./client";
import type { ExportJob } from "./types";

export const accountApi = {
  /** AC-2. Each change is written to the audit log. */
  setConsent: async (trainingConsent: boolean) =>
    unwrap(await apiClient.PUT("/account/consent", { body: { training_consent: trainingConsent } })),
  /** AC-1. A background job prepares a zip; poll getExport until the status is "ready". */
  startExport: async () => unwrap(await apiClient.POST("/account/export")) as ExportJob,
  getExport: async (exportId: string) =>
    unwrap(
      await apiClient.GET("/account/export/{export_id}", { params: { path: { export_id: exportId } } }),
    ) as ExportJob,
  /** AC-1. Rows are deleted at once; resume files within 24 hours. */
  deleteAccount: async () => unwrap(await apiClient.DELETE("/account")),
};
