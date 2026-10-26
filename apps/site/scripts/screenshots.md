# How it works: screenshots

The three images in `public/img/` (gap analysis, live interview, debrief) come from the web app
running on its mock API, so they show made-up data. A fictional company name replaces the mock's
company, and dev-only links are removed (Q3: no real company names in images).

To retake them, from `apps/web`:

```powershell
Copy-Item ../site/scripts/screenshots.spec.ts.txt e2e/zz-site-shots.spec.ts
pnpm exec playwright test e2e/zz-site-shots.spec.ts
Remove-Item e2e/zz-site-shots.spec.ts
```
