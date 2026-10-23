import { useEffect, useState } from "react";

import { useSiteStatus } from "../api/status";

/**
 * OC-4: the site banner the ops team sets in the admin app, on every page. It hides itself at its
 * end time, even before the next status refresh.
 */
export function SiteBanner() {
  const status = useSiteStatus();
  const banner = status.data?.banner ?? null;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!banner) return;
    const left = Date.parse(banner.until) - Date.now();
    if (!(left > 0)) return;
    // setTimeout takes at most about 24.8 days; a later end time is checked again on refresh.
    const t = setTimeout(() => setNow(Date.now()), Math.min(left + 50, 2 ** 31 - 1));
    return () => clearTimeout(t);
  }, [banner]);

  if (!banner || !(Date.parse(banner.until) > now)) return null;
  return (
    <div
      className="site-banner"
      data-severity={banner.severity}
      role={banner.severity === "critical" ? "alert" : "status"}
      aria-label="Site notice"
    >
      <p>{banner.text}</p>
    </div>
  );
}
