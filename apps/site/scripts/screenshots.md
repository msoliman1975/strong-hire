# How it works: screenshots

The six `v2-*.jpg` images in `public/img/` (Home, story workbench, coach session, interview plan,
live room, debrief) come from the web app running on its mock API with `v2_enabled` on, so they show made-up data
(Q3: no real company names in images). The spec turns the flag on
without a code change: an init script sets `siteStatus.v2_enabled` in the mock database that MSW
keeps in localStorage, so the mock `GET /status` returns it. The spec signs up, adds the job and
CV, sets an interview date, runs two mini interviews, builds a story with the coach and adds a
reflection and two takes to a seed story. Company names become "Northwind" and `(dev)` links are
removed before each shot.

To retake them, from `apps/web`:

```powershell
Copy-Item ../site/scripts/screenshots-v2.spec.ts.txt e2e/zz-site-shots-v2.spec.ts
pnpm exec playwright test e2e/zz-site-shots-v2.spec.ts
Remove-Item e2e/zz-site-shots-v2.spec.ts
```
