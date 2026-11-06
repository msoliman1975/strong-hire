# LLM tracing phase 2: legal gates (LT-30, D-17)

Production tracing ships switched off. Each flag goes on only when its gate is met. The owner
ticks the boxes and records the date; nobody turns a flag on with a box open.

This is a planning checklist, not legal advice. The privacy lawyer confirms each point.

## Gate 1: `LLM_TRACING_PROD=on` (metadata for every session)

Metadata traces hold no message text, but they are tied to a session and so to a person.

- [ ] The privacy policy says, in plain language, that the service records how each interview ran
      (timings, cost, model and prompt versions, errors), not what was said, to keep it working
      and improve it; where it is stored (the same server in Germany); and for how long (90 days).
- [ ] The retention schedule lists production metadata traces: 90 days, deleted with the account.
- [ ] The PIA for the Strong Hire system lists MLflow as a store of session metadata.
- [ ] Gate met on: ____ (date, owner)

## Gate 2: `LLM_TRACING_PROD_CONTENT=on` (consent toggle and content)

- [ ] The consent wording is approved by the privacy lawyer. It says, at least:
  - what is kept: what the interviewer said and what you answered in each interview, with your
    name, emails, phone numbers and the companies you listed removed (best effort);
  - what is not kept: your resume, the job posting, your scores;
  - why: so the team can review interviews and make the interviewer better;
  - who sees it: Strong Hire admins, each view recorded;
  - how long: 30 days;
  - that it is off unless you turn it on, and that turning it off deletes what was kept within
    24 hours.
- [ ] The privacy policy describes the opt-in and links to the toggle.
- [ ] The retention schedule lists production content traces: 30 days, deleted on withdrawal and
      with the account.
- [ ] The PIA update covers content traces: sensitivity, purpose, access (admins only, audited),
      retention, deletion, and the scrubbing limits.
- [ ] Gate met on: ____ (date, owner)
