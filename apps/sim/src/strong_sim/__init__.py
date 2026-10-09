"""The AI candidate (P13). It takes interviews against the deployed app, as a real user would.

    strong-sim run --suite text-smoke

A run reads a suite of scenarios (evals/scenarios/<suite>.yaml), signs in as the sim user, and
for each scenario: starts a session, lets the candidate model answer the interviewer (text or
voice), ends the session, waits for the debrief, asks the judge model to check the interviewer,
and saves the transcript, audio, verdict and debrief. The run ends with a report.
"""
