"""Suggestions from Strova (ux-spec section 8, SG-2 to SG-7): the worker side.

- `facts`: the no-new-facts check (CO-9, SG-7) every model-written text passes before it is
  stored.
- `store`: adds a suggestion unless one of the same kind, source and target exists in any
  status, so a dismissed suggestion never comes back (SG-8).
- `generate`: the coach-role calls, prompts `coach/suggest_*` and `coach/review`.
- `after_take`: the step score_session runs after the story step: tune a story (SG-2), new story
  (SG-3), missing skill (SG-4, rule-based).
- `tailor`: tailor for a role (SG-5), after story fit computes a new table.
- `jobs`: the Arq jobs for improve resume line (SG-6) and review (ST-11).
"""
