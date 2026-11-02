/**
 * RP-9: after a role-play, what the buyer was hiding. The API sends the full buyer brief only once
 * the session has ended, so this never shows during the call.
 */
import type { SessionRecord } from "../../api/types";
import { rolePlayScenarioLabel } from "../../labels";

export function BuyerReveal({ buyer: who }: { buyer: SessionRecord["buyer"] }) {
  const buyer = who?.reveal;
  if (!buyer) return null;
  return (
    <section className="sx-card" aria-labelledby="buyer-reveal-heading">
      <div className="sx-eyebrow teal">{rolePlayScenarioLabel[buyer.scenario]}</div>
      <h2 id="buyer-reveal-heading">What {buyer.persona_name} was hiding</h2>
      <p className="sx-small sx-muted">
        {buyer.persona_title}. {buyer.company_summary} {buyer.situation}
      </p>
      <h3>The problems a good question would uncover</h3>
      <ul>
        {buyer.hidden_pains.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      <h3>The objections</h3>
      <ul>
        {buyer.objections.map((o) => (
          <li key={o.text}>
            {o.text} <span className="sx-small sx-muted">({o.when})</span>
          </li>
        ))}
      </ul>
      <p>
        <strong>What earned the next step:</strong> {buyer.success_condition}
      </p>
    </section>
  );
}
