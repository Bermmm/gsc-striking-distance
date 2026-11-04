# gsc-striking-distance

Find the Google Search Console pages and queries that are **almost** on page one, and rank them by how many clicks you're missing.

Pages sitting around positions 8–20 already have Google's attention. They're relevant, just not high enough to get clicked. Moving them up a few spots is usually easier than ranking something new from zero. This script finds them in your Search Console export and tells you which to fix first.

**One Python file. No installs. No API keys.** Works on the export you can download from Search Console in 10 seconds.

## What it finds

| Section | What it tells you |
|---|---|
| **Summary** | Clicks, impressions and average position for the first vs last 4 weeks of the export |
| **Pages in striking distance** | Pages ranking 8–20, sorted by potential clicks if they moved to position 3 |
| **Queries in striking distance** | Same for queries, plus how much of your traffic the query table actually covers |
| **Page-one pages with weak CTR** | Top-10 pages getting less than half the expected click-through. Usually a title/snippet problem |
| **Where impressions come from** | Impressions, clicks and position by site section (`/blog/`, `/products/` and so on) |
| **Machine-like queries** | 20+ word queries that look like prompts from AI tools searching on someone's behalf |

## Use it

1. In Search Console, go to **Performance → Search results**, pick a date range (3 months works well) and click **Export → Download CSV**.
2. Run:

```bash
python3 gsc_striking_distance.py your-export.zip
```

That writes `striking-distance-report.md`. Point it at the `.zip` or an unzipped folder.

Options:

```bash
python3 gsc_striking_distance.py export.zip \
  --out report.md \        # where to write the report
  --csv out/ \             # also save the striking-distance rows as CSV
  --min-pos 8 --max-pos 20 \  # the position window
  --min-impr 20 \          # ignore pages with fewer impressions
  --target 3               # position used to estimate potential clicks
```

Needs Python 3.8+.

## Real example

[`examples/carlens-report.md`](examples/carlens-report.md) is the output for [carlens.ca](https://carlens.ca), a used-car listing checker I built, using 3 months of data (Aug–Oct 2026). Highlights:

- **75 pages** were in striking distance. The top one, a guide to negotiating a used-car price in Canada, had 261 impressions at position 9.6 and 1 click.
- **90% of impressions** came from programmatic `/cars/make/model/year` pages, at an average position of 18.
- The query table covered only **17% of impressions**, because Search Console hides rare queries. That's why the page tables matter more.
- It caught **4 queries over 100 words long** that read like AI-agent prompts, not human searches.

## How "potential clicks" works

`potential clicks = impressions × benchmark CTR at the target position − current clicks`

The CTR benchmarks (`CTR_CURVE` at the top of the script) are rough industry ballparks, not data from your site. Real click-through varies with the query, the result layout and whether an AI Overview answers it first. Use the numbers to **rank what to fix**, not as a traffic forecast. If you have better CTR data for your niche, edit the curve.

## Privacy

Everything runs locally. Your export never leaves your computer. `.gitignore` excludes `.zip` and `exports/` so you don't commit raw data by accident.

## License

MIT. Built by [Brayden Berman](https://bberm.work).
