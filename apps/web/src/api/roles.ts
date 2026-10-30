/**
 * Target roles, interviews and readiness per interview (U06: TG-3, RH-1, RH-2). Real API endpoints.
 */
import { apiClient, unwrap } from "./client";
import type { RoleOut } from "./types";

export const rolesApi = {
  /** TG-1: every live role with one readiness per interview, newest first. */
  list: async () => unwrap(await apiClient.GET("/roles")) as RoleOut[],
};
