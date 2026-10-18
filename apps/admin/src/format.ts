/** Formatting for the admin pages. Times are shown in UTC so every admin sees the same value. */

export function utc(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function clock(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "-";
  const sign = ms < 0 ? "-" : "";
  const total = Math.floor(Math.abs(ms) / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return `${sign}${minutes}:${seconds}`;
}

export function money(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "Unknown";
  return `$${usd.toFixed(4)}`;
}

export function words(code: string): string {
  return code.replace(/_/g, " ");
}
