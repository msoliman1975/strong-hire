# Strong Hire Admin: UI standard

The rules every admin page follows. They borrow from established systems so nobody has to
invent spacing or button rules per page: the 4 px grid and type scale of IBM Carbon and GitHub
Primer, Carbon's button hierarchy, BEM class names, and WCAG 2.2 AA for contrast and targets.

The CSS lives in `src/styles/`, imported in this order by `src/styles.css`:

| File | Contents |
| --- | --- |
| `tokens.css` | Every color, size, radius and shadow, light and dark. The only file with raw values. |
| `base.css` | Element defaults (type, links, focus). No classes. |
| `layout.css` | Shell, sidebar, page header, sections, stacking, helpers. |
| `components.css` | Buttons, fields, panels, badges, notices, tabs, dialog, meter. |
| `data.css` | Tables, key-value lists, KPI tiles, funnel, charts, status tiles, diffs. |
| `features.css` | Pieces for one page (controls, simulations, replay, content, settings). |

`pnpm lint` runs stylelint (`stylelint-config-standard` plus BEM names) on all of them, so a
syntax error such as a missing `}` fails CI. Two merges in October dropped a brace and silently
turned off half the stylesheet; the linter is there so that cannot happen again.

## Tokens

- **Spacing:** a 4 px grid: `--space-2` 4, `--space-3` 8, `--space-4` 12, `--space-5` 16,
  `--space-6` 24, `--space-7` 32, `--space-8` 48. (`--space-1` is 2 px, for hairline gaps.)
- **Type:** 14 px base. Scale: `--text-xs` 12, `--text-sm` 13, `--text-md` 14, `--text-lg` 16,
  `--text-xl` 20, `--text-2xl` 24. Weights 400, 500 and 600 (700 only for the brand).
  Numbers in tables and tiles use tabular figures.
- **Color:** semantic names, never hex in components. `--ink`, `--ink-2`, `--muted` for text;
  `--surface`, `--surface-2`, `--surface-3` for fills; `--accent`, `--danger`, `--warn`, `--ok`
  with a matching `-bg` for subtle fills. Text meets 4.5:1 on its surface, borders and focus
  rings 3:1, in both themes. Amber (`--admin`) marks the admin app and nothing else.
- **Shape:** radius 4 (small labels), 6 (controls), 8 (panels); `--shadow-1` on cards,
  `--shadow-2` on dialogs and tooltips.

## Layout

- The sidebar is fixed, full height, 232 px; the content area has 32 px padding and a
  1440 px maximum width.
- Every page starts with `PageHead`: a 24 px title and a one-line muted description. Page-wide
  controls (the time range) go right under it.
- A page is a column of `section.section` blocks, 32 px apart, each with an `h2` (16 px). An
  intro sentence under the `h2` is muted.
- Content blocks (`.panel`, `.table-wrap`, `.kpis`, `.tiles`, `.funnel`, `.grid-2`, `.split`)
  stack 16 px apart automatically. Use `.grid-2` or `.split` to put panels side by side.

## Components

**Buttons.** One height per size: 36 px (default) and 28 px (`.btn--small`), so buttons
line up with inputs.

| Class | Use |
| --- | --- |
| `.btn--primary` | The one main action of a form or panel (Search, Start run, Save). |
| `.btn` | Every other action (secondary). |
| `.btn--ghost` | Low-emphasis actions in toolbars and the sidebar. |
| `.btn--danger-outline` | Opens a destructive or high-impact action (Suspend, Delete, Pause sign-ups). |
| `.btn--danger` | Confirms that action, inside the confirm dialog only. |
| `.btn--link` | An action that reads as a link. |

A page never shows a filled red button: red fill means "this happens now".

**Forms.** Label above the field (13 px, 600), 4 px apart; fields 16 px apart; inputs and
selects 36 px high. Lay fields out with `.form-grid` (a form) or `.filters` (a filter bar
above a table). Help text is 12 px muted. Group related fields in `fieldset.section`.

**Panels.** `.panel` is the card: white surface, 1 px line, radius 8, 16/24 px padding.

**Labels.** Badges, status pills, states and tags share one shape: 20 px high, 12 px, pill.
Color comes from `data-status` or `data-state`, using the semantic `-bg` and solid colors.

**Notices.** `.notice` (info), `.notice--error`, `.ops-banner` (warning): subtle fill and a
3 px colored left rule.

**Dialogs.** Title 20 px, a summary box of what will happen, then actions right-aligned
behind a divider, with Cancel before the confirm button.

## Data

- **Tables** are always inside `.table-wrap`. Text left, numbers right (`.num`). Header row
  12 px uppercase, muted, sticky. No vertical rules; a row highlights on hover.
- **Key-value lists** use `dl.dl`: muted 13 px terms, values in the base size.
- **KPI tiles** (`.kpi`): label, 24 px value, delta and target in 12 px. An unmeasured metric
  gets a dashed tile.
- **Charts** draw at their real pixel width, so tick labels are always 11 px. Series colors
  are `--series-1` to `--series-3`; every multi-series chart has a legend and a table view.
- **Health tiles** (`.tile`) carry a 3 px left rule in the status color.

## Checklist for a new page

1. `PageHead` with a title and one sentence.
2. Sections with `h2`; content in panels, tables or tiles, no bare text blocks.
3. At most one primary button per panel; red only as described above.
4. Only tokens in new CSS, BEM class names, and `pnpm lint` passes.
5. Look at it in both themes and at 760 px wide.
