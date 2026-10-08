import { useMutation } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import { billingApi } from "../api/billing";
import { usePlan, useUsage } from "../api/hooks";
import { ErrorNotice, Loading, PageHead } from "../components/ui";

const REASONS: Record<string, string> = {
  upgrade_required: "You have used your free mini interviews. Gap analyses stay free.",
  minutes_exhausted: "You have used this month's interview minutes.",
  full_interview_requires_plan:
    "Full interviews (30 and 45 minutes) are part of the subscription. Free accounts get mini interviews.",
};

/** BL-1 and BL-2: the monthly plan. Prices and caps come from the API. */
export function PaywallPage() {
  const [params] = useSearchParams();
  const plan = usePlan();
  const usage = useUsage();
  const checkout = useMutation({
    mutationFn: billingApi.checkout,
    onSuccess: ({ url }) => window.location.assign(url),
  });
  const reason = params.get("reason");

  return (
    <div className="page--narrow">
      <PageHead title="Keep practicing">
        {reason && <p>{REASONS[reason] ?? REASONS.upgrade_required}</p>}
      </PageHead>
      {plan.isPending && <Loading />}
      {plan.isError && <ErrorNotice error={plan.error} />}
      {plan.data && (
        <section className="panel" aria-labelledby="plan-heading">
          <div className="plan">
            <div>
              <h2 id="plan-heading">{plan.data.name}</h2>
              <ul>
                <li>{plan.data.minutes_cap} interview minutes each month</li>
                <li>Full 30 and 45 minute interviews, and 10 minute mini interviews</li>
                <li>All four interview types, Coach and Realistic modes</li>
                <li>Unlimited gap analyses</li>
                <li>Cancel at any time</li>
              </ul>
            </div>
            <p className="plan__price">
              ${plan.data.price_usd_month}
              <small> per month</small>
            </p>
          </div>
          {usage.data?.plan === "paid" ? (
            <p className="notice notice--ok">Your plan is already active.</p>
          ) : plan.data.billing_enabled ? (
            <button type="button" className="btn" onClick={() => checkout.mutate()} disabled={checkout.isPending}>
              Subscribe
            </button>
          ) : (
            <p className="notice" role="status">
              Payments are not set up yet. Try again later.
            </p>
          )}
          {checkout.isError && <ErrorNotice error={checkout.error} />}
          <p className="muted section">Payment is handled by Stripe. We do not see or store your card details.</p>
        </section>
      )}
    </div>
  );
}
