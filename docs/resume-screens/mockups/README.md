# Approved mockups (RMAP-9)

These are copies of the three approved boards from the design canvas
<https://claude.ai/artifact/Hi9y2agVNadm9cmKLwhmWt>, approved by the owner on 2026-11-03.

| File | Canvas board | Screen |
| --- | --- | --- |
| `resumes-list.dc.html` | Resumes list (2 columns) | `/resumes` |
| `target-roles.dc.html` | Target roles (shared card shell) | `/roles` |
| `check-resume.dc.html` | Check C2: Guided, revised (v2) | `/resumes/:id/check` |

They are Design Component files: they need the canvas runtime (`./support.js`), so open the canvas
to see them work. Read the markup for order, copy and states. The colours are literal hex values
copied from `apps/web/src/theme/tokens.css`; in code, use the `--sh-*` tokens. The sample data
(names, companies, dates) is illustrative only.
