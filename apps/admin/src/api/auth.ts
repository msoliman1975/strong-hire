/**
 * Admin sign-in (AA-2, AA-3): the admin app's own routes under /admin/auth, with a server-side
 * admin session in the `sh_admin` cookie. The candidate sign-in is never used here (AA-4).
 */
import { API_BASE, apiClient, unwrap } from "./client";
import type { AdminMe } from "./types";

export const authApi = {
  /** The signed-in admin, or null when there is no live admin session (the API answers 401). */
  me: async (): Promise<AdminMe | null> => {
    const result = await apiClient.GET("/admin/me");
    if (result.response.status === 401) return null;
    return unwrap(result);
  },
  providers: async () => unwrap(await apiClient.GET("/admin/auth/providers")),
  passwordLogin: async (body: { email: string; password: string }) =>
    unwrap(await apiClient.POST("/admin/auth/password", { body })),
  sendMagicLink: async (email: string) => unwrap(await apiClient.POST("/admin/auth/link", { body: { email } })),
  verifyLink: async (token: string) => unwrap(await apiClient.POST("/admin/auth/link/verify", { body: { token } })),
  logout: async () => {
    const result = await apiClient.POST("/admin/auth/signout");
    if (!result.response.ok) unwrap(result);
  },
  /** Full-page navigation: Google sign-in is a redirect flow, and its callback is on this host. */
  googleLoginUrl: `${API_BASE}/admin/auth/google/login`,
};
