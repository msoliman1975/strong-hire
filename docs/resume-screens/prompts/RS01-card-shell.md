# RS01 · Shared card shell and stat tiles

- **Branch:** `feat/rs-01-card-shell`
- **Waits for:** RS00.
- **Owns:** `apps/web/src/components/ux/` (a new `SummaryCard.tsx`, `ux.css`, its tests).
- **Requirement IDs:** RS-5.

## Goal

One card component that both list pages use, so Resumes and Target roles look like one product.

## Read first

- Spec D-2, D-3 and RS-1 to RS-5.
- Mockup boards "Resumes list (2 columns)" and "Target roles (shared card shell)".
- `ux.css` (`sx-card`, `sx-chip`, `sx-btn`, `sx-grid2`), `theme/tokens.css`.

## Build

1. `SummaryCard`, a `<section aria-labelledby>`. Its props:
   - `title` (an h2), `chip` (optional node) and `stats` (exactly three `StatTile` items);
   - `meta` (optional text), `children` (an optional body, for the readiness bars);
   - `primary` (the Show details link) and `actions` (an optional node: buttons on the right);
   - `loading` (draws empty tiles and hides the stats).
2. `StatTile`: `value` (number or "—"), `label` and `tone` (`neutral`, `warn` or `teal`). The
   `warn` tone draws the ▲ mark as `role="img"` with the label from `markLabel`. Render the tiles
   as a `<dl>`, each `<dt>` holding the label, with the value shown first. Tiles are never
   interactive.
3. CSS in `ux.css`, as `sx-summary`, `sx-stat` and `sx-summary__foot`, using `--sh-*` tokens only:
   - tiles: ground fill, 12 px radius, mono 26 px value;
   - the footer: a top rule, Show details on the left and the actions on the right; it wraps on
     phones;
   - the grid is `sx-grid2` with `align-items: stretch`.
4. An `AddCard`: the dashed "+ title / hint" link card that ends a grid.
5. **Tests:** render with each tone, the loading state and the actions slot; the ▲ label is
   announced; nothing inside the stats is focusable.

## Done when

- The RS-5 tests pass.
- The component is exported and not used by any page yet. RS02 and RS03 adopt it.
