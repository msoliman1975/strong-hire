import { API_BASE, apiClient, unwrap } from "./client";

export const authApi = {
  me: async () => unwrap(await apiClient.GET("/auth/me")),
  providers: async () => unwrap(await apiClient.GET("/auth/providers")),
  devLogin: async (email: string) =>
    unwrap(await apiClient.POST("/auth/dev-login", { body: { email } })),
  sendMagicLink: async (email: string) =>
    unwrap(await apiClient.POST("/auth/magic-link", { body: { email } })),
  passwordSignup: async (body: {
    email: string;
    password: string;
    full_name: string | null;
    age_confirmed: boolean;
    terms_accepted: boolean;
  }) =>
    // AC-2: training-data consent starts off; the user can turn it on under Account.
    unwrap(await apiClient.POST("/auth/password/signup", { body: { ...body, training_consent: false } })),
  passwordLogin: async (body: { email: string; password: string }) =>
    unwrap(await apiClient.POST("/auth/password/login", { body })),
  resendConfirmation: async (email: string) =>
    unwrap(await apiClient.POST("/auth/password/resend", { body: { email } })),
  forgotPassword: async (email: string) =>
    unwrap(await apiClient.POST("/auth/password/forgot", { body: { email } })),
  resetPassword: async (body: { token: string; password: string }) =>
    unwrap(await apiClient.POST("/auth/password/reset", { body })),
  signup: async (body: { age_confirmed: boolean; terms_accepted: boolean; training_consent: boolean }) =>
    unwrap(await apiClient.POST("/auth/signup", { body })),
  logout: async () => {
    const result = await apiClient.POST("/auth/logout");
    if (!result.response.ok) unwrap(result);
  },
  /** Full-page navigation: Google sign-in is a redirect flow. */
  googleLoginUrl: `${API_BASE}/auth/google/login`,
};
