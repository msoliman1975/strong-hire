import type { ReactNode } from "react";
import { Navigate } from "react-router";

import { useFeature } from "../../theme/features";

/** The story pages are new in v2: with `v2_enabled` off they send the user Home. */
export function V2Only({ children }: { children: ReactNode }) {
  return useFeature("v2_enabled") ? <>{children}</> : <Navigate to="/" replace />;
}
