import type { Scorecard } from "../../api/types";

/**
 * DM-2 slot for S24: delivery metrics for the session. Empty until S24 fills it; S24 edits this
 * file only. Each answer's `delivery` comes from the scorecard.
 */
export function DeliveryMetrics({ scorecard }: { scorecard: Scorecard }) {
  void scorecard;
  return null;
}
