# Roadmap

Product items to build later. Each item has an ID (`RM-N`) so specs, execution plans and PRs can
refer to it. When an item gets requirement IDs in a spec, list them under Notes.

Fields: **Area** (api, worker, voice, web, core, prompts, infra), **Priority** (Now, Next, Later),
**Status** (Idea, Planned, In progress, Done).

| ID | Title | Area | Priority | Status |
| --- | --- | --- | --- | --- |
| RM-1 | Filter Rehearsals by target role | web | Next | Idea |

## RM-1: Filter Rehearsals by target role

**Recorded:** 2026-11-02

**What:** On **Rehearsals with Strova** (`#rehearse`, `docs/ux-strova/ux-spec.md` section 6.5),
add a filter by job posting (target role). The default is **All**, which shows every interview
across roles, as the page does today. Picking one target role shows only that role's interviews.

**Why:** A user with several target roles sees one long list of interviews and can't easily focus
on the role they're preparing for next.

**Notes:**

- User-facing copy says "Target role", not "JD" (ux-spec section 3).
- Each interview already belongs to one target role (Target role × Resume × Type), so the list may
  be filterable on the client from data the page already loads. Check before adding an API change.
- Open questions: should the recommended next-take hero follow the filter? Should the filter be
  remembered between visits, or set from a role page link (for example `#rehearse?role=<id>`)?
