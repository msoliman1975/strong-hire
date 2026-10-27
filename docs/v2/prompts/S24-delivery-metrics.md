# S24 · Delivery metrics

- **Branch:** `feat/v2-s24-delivery-metrics`
- **Wave:** 2. **Waits for:** C2 and S12.
- **Owns:** `apps/worker/src/strong_worker/scoring/delivery.py` (new) and one call to it in the
  scoring pipeline, `apps/web/src/pages/debrief/Delivery*`.
- **Requirement IDs:** DM-1, DM-2.

## Goal

Candidates see their speaking pace and filler words per answer, computed without any audio.

## Read first

- Spec: "Data handling", the Turn entity (`start_ms`, `end_ms`), and "Later releases: delivery
  metrics".
- `apps/worker/src/strong_worker/scoring/`.

## Build

1. In code, with no model call: for each answer, take the candidate's turns, then compute words
   per minute and fillers per minute. Use a fixed English filler list in one constant ("um",
   "uh", "like" as a filler, "you know", "basically", "sort of"). Store `DeliveryMetrics` per
   question.
2. Skip text-channel sessions (PL-7), where timing is not speech, and say so on the debrief.
3. Debrief section (DM-2): pace and fillers per answer, with a plain note when they are outside a
   normal range (keep the ranges in one constant, documented in the code).

## Done when

Unit tests cover DM-1 with fixed turn data (including the text-channel skip); web tests cover DM-2.
