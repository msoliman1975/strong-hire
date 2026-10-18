import { useQuery } from "@tanstack/react-query";

import { apiClient, unwrap } from "./client";
import type { Health } from "./types";

export const healthApi = {
  get: async () => unwrap(await apiClient.GET("/health")) as unknown as Health,
};

/** The environment label in the header: which model profile this server runs (D-11, OC-6). */
export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: healthApi.get, staleTime: 60_000, retry: false });
