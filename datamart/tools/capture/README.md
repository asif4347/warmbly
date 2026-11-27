# Capture scripts

Playwright helpers for the demo films and landing checks. They import from
`qa/lib` and use the `qa` package's Playwright, so copy them in before running
and delete the copies afterwards:

```bash
cp datamart/tools/capture/*.ts qa/scripts/
cd qa
npx tsx scripts/brag-probe.ts <out-dir> /app/campaigns=campaigns ...
npx tsx scripts/brag-actions.ts <out-dir> [shot names]
npx tsx scripts/landing-check.ts "$PWD/../datamart/landing/index.html" <out-dir>
```

`brag-probe` and `brag-actions` sign in to the local sandbox with upstream's
public seed login and refuse to run against anything but localhost. Set
`DSF=2` for 2x screenshots. `landing-check` needs no stack: it opens the page
from disk at desktop, phone and dark sizes and reports overflow and errors.
