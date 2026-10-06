import { API_BASE, apiClient, unwrap } from "./client";

export const authApi = {
  me: async () => unwrap(await apiClient.GET("/auth/me")),
  providers: async () => unwrap(await apiClient.GET("/auth/providers")),
  devLogin: async (email: string) =>
    unwrap(await apiClient.POST("/auth/dev-login", { body: { email } })),
  sendMagicLink: async (email: string) =>
    unwrap(await apiClient.POST("/auth/magic-link", { body: { email } })),
  signup: async (body: { age_confirmed: boolean; terms_accepted: boolean; training_consent: boolean }) =>
    unwrap(await apiClient.POST("/auth/signup", { body })),
  logout: async () => {
    const result = await apiClient.POST("/auth/logout");
    if (!result.response.ok) unwrap(result);
  },
  /** Full-page navigation: Google sign-in is a redirect flow. */
  googleLoginUrl: `${API_BASE}/auth/google/login`,
};
