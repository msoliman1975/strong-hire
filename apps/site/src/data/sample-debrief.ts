/**
 * Q7: the sample debrief. Shaped like the app's Scorecard (packages/core strong_core.schemas).
 *
 * PLACEHOLDER: replace with the real debrief of a simulator run (an "average quality" simulated
 * candidate in a behavioral session) before the domain switch. Until then the page says it is an
 * illustration. No real person's answers appear here.
 */
export const SAMPLE_IS_PLACEHOLDER = true;

export const sample = {
  interview: "Behavioral interview, senior level, 30 minutes",
  hire_signal: "Lean Hire" as const,
  rationale:
    "Clear ownership of a large migration and good use of numbers. The answers were weaker on conflict: two of three stories ended before saying how the disagreement was resolved, which the bar for this level expects.",
  competencies: [
    { name: "Ownership", score: 3, note: "Took on the migration without being asked and saw it through." },
    { name: "Impact", score: 3, note: "Gave a before and after number for checkout errors." },
    { name: "Collaboration", score: 3, note: "Named the partner teams and how work was split." },
    { name: "Conflict handling", score: 2, note: "Did not say how the disagreement with the platform team ended." },
    { name: "Trade-offs", score: 2, note: "Chose a phased rollout but did not say what it cost." },
  ],
  questions: [
    {
      question: "Tell me about a time you led a project you did not formally own.",
      score: 3,
      evidence: "“I owned the migration end to end and cut checkout errors by 40 percent.”",
      feedback: "Strong ownership and a clear result. Add what you would do differently: the bar for this level expects reflection.",
    },
    {
      question: "Describe a disagreement with another team. How was it resolved?",
      score: 2,
      evidence: "“We went back and forth for a while, and then we moved on to the next milestone.”",
      feedback: "The story stops before the resolution. Say what you proposed, who decided, and what changed afterwards.",
    },
    {
      question: "Tell me about a decision you made with incomplete data.",
      score: 3,
      evidence: "“We shipped to 5 percent of traffic first, because we could not test the fraud rules offline.”",
      feedback: "Good use of a staged rollout. Name the risk you accepted and how you would have known it went wrong.",
    },
  ],
  fix_first: [
    "End every conflict story with the outcome and what you learned.",
    "State the cost of each trade-off, not only the choice.",
    "Close each story with one sentence on what you would do differently.",
  ],
};
