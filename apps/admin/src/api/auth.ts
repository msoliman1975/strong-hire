/**
 * Sign-in for the admin app. For now it uses the candidate sign-in routes, served on the admin
 * host, and the `is_admin` flag (ADMIN_EMAILS). `app=admin` makes email links and Google
 * sign-in come back to this host. A later PR swaps in dedicated admin sessions (AA-2, AA-3).
 */
import { API_BASE, apiClient, unwrap } from "./client";

export const authApi = {
  me: async () => unwrap(await apiClient.GET("/auth/me")),
  providers: async () => unwrap(await apiClient.GET("/auth/providers")),
  devLogin: async (email: string) => unwrap(await apiClient.POST("/auth/dev-login", { body: { email } })),
  passwordLogin: async (body: { email: string; password: string }) =>
    unwrap(await apiClient.POST("/auth/password/login", { body })),
  sendMagicLink: async (email: string) =>
    unwrap(await apiClient.POST("/auth/magic-link", { params: { query: { app: "admin" } }, body: { email } })),
  logout: async () => {
    const result = await apiClient.POST("/auth/logout");
    if (!result.response.ok) unwrap(result);
  },
  /** Full-page navigation: Google sign-in is a redirect flow. */
  googleLoginUrl: `${API_BASE}/auth/google/login?app=admin`,
};
