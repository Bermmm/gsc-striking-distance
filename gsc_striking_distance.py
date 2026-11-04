#!/usr/bin/env python3
"""
gsc-striking-distance: find the Google Search Console queries and pages
that are closest to page one and worth fixing first.

Usage:
    python3 gsc_striking_distance.py path/to/export.zip
    python3 gsc_striking_distance.py path/to/export-folder --out report.md

Input is the standard "Export" from the Search Console Performance report
(Google Sheets/CSV/zip). Only the Python standard library is used.
"""

import argparse
import csv
import io
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

# Rough organic click-through rate by position. These are ballpark benchmark
# values, not measurements from your site. Real CTR varies a lot by query
# type, SERP features and AI Overviews. Edit them if you have better numbers.
CTR_CURVE = {
    1: 0.28, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05,
    6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.018,
}
CTR_PAGE_TWO = 0.01  # positions 11-20
CTR_BEYOND = 0.003   # positions 21+

LONG_QUERY_WORDS = 20  # queries longer than this look machine-generated


# ---------- loading ----------

def read_export(path):
    """Return {filename_lower: list_of_dict_rows} from a zip or a folder."""
    path = Path(path)
    tables = {}
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(".csv"):
                    text = z.read(name).decode("utf-8-sig")
                    tables[Path(name).name.lower()] = list(csv.DictReader(io.StringIO(text)))
    elif path.is_dir():
        for f in path.glob("*.csv"):
            tables[f.name.lower()] = list(csv.DictReader(f.open(encoding="utf-8-sig")))
    else:
        sys.exit(f"Not a .zip or folder: {path}")
    return tables


def num(value):
    value = (value or "").strip().replace(",", "")
    if value.endswith("%"):
        return float(value[:-1]) / 100
    try:
        return float(value)
    except ValueError:
        return 0.0


def normalize(rows, key_header):
    """Turn GSC rows into dicts with key, clicks, impressions, ctr, position."""
    out = []
    for r in rows:
        key = r.get(key_header)
        if key is None:
            continue
        clicks, impr = num(r.get("Clicks")), num(r.get("Impressions"))
        out.append({
            "key": " ".join(key.split()),  # collapse multi-line queries
            "clicks": int(clicks),
            "impressions": int(impr),
            "ctr": clicks / impr if impr else 0.0,
            "position": num(r.get("Position")),
        })
    return out


# ---------- analysis ----------

def expected_ctr(position):
    p = max(1, round(position))
    if p in CTR_CURVE:
        return CTR_CURVE[p]
    return CTR_PAGE_TWO if p <= 20 else CTR_BEYOND


def striking_distance(rows, lo, hi, min_impr, target):
    """Rows ranking between lo and hi, scored by clicks they could gain at `target`."""
    hits = []
    for r in rows:
        if lo <= r["position"] <= hi and r["impressions"] >= min_impr:
            gain = r["impressions"] * expected_ctr(target) - r["clicks"]
            hits.append({**r, "gain": max(0.0, gain)})
    return sorted(hits, key=lambda r: (-r["gain"], r["position"]))


def low_ctr(rows, max_pos, min_impr):
    """Rows already on page one whose CTR is well under the benchmark."""
    hits = []
    for r in rows:
        if r["position"] <= max_pos and r["impressions"] >= min_impr:
            exp = expected_ctr(r["position"])
            if r["ctr"] < exp * 0.5:
                hits.append({**r, "expected": exp, "missed": r["impressions"] * exp - r["clicks"]})
    return sorted(hits, key=lambda r: -r["missed"])


def page_group(url):
    m = re.match(r"https?://[^/]+(/[^/?#]*)?", url)
    seg = (m.group(1) if m and m.group(1) else "/").strip("/")
    return "/" if not seg else f"/{seg}/"


def group_pages(pages):
    groups = defaultdict(lambda: {"pages": 0, "clicks": 0, "impressions": 0, "pos_w": 0.0})
    for p in pages:
        g = groups[page_group(p["key"])]
        g["pages"] += 1
        g["clicks"] += p["clicks"]
        g["impressions"] += p["impressions"]
        g["pos_w"] += p["position"] * p["impressions"]
    total = sum(g["impressions"] for g in groups.values()) or 1
    out = []
    for name, g in groups.items():
        out.append({
            "group": name, **g,
            "share": g["impressions"] / total,
            "position": g["pos_w"] / g["impressions"] if g["impressions"] else 0.0,
        })
    return sorted(out, key=lambda g: -g["impressions"])


def trend(chart_rows, window=28):
    """Compare the first and last `window` days of the export."""
    days = []
    for r in chart_rows:
        impr = num(r.get("Impressions"))
        days.append({"date": r.get("Date"), "clicks": num(r.get("Clicks")), "impr": impr,
                     "pos_w": num(r.get("Position")) * impr})
    if len(days) < window * 2:
        window = max(1, len(days) // 2)

    def summarize(chunk):
        impr = sum(d["impr"] for d in chunk)
        return {"from": chunk[0]["date"], "to": chunk[-1]["date"],
                "clicks": int(sum(d["clicks"] for d in chunk)), "impr": int(impr),
                "position": sum(d["pos_w"] for d in chunk) / impr if impr else 0.0}

    return summarize(days[:window]), summarize(days[-window:]), {
        "from": days[0]["date"], "to": days[-1]["date"],
        "clicks": int(sum(d["clicks"] for d in days)), "impr": int(sum(d["impr"] for d in days)),
        "position": sum(d["pos_w"] for d in days) / (sum(d["impr"] for d in days) or 1)}


# ---------- output ----------

def short(text, n=70):
    return text if len(text) <= n else text[: n - 1] + "…"


def path_only(url):
    return re.sub(r"^https?://[^/]+", "", url) or "/"


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---:" if i else "---" for i in range(len(headers))) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def build_report(t, args):
    queries = normalize(t.get("queries.csv", []), "Top queries")
    pages = normalize(t.get("pages.csv", []), "Top pages")
    chart = t.get("chart.csv", [])
    out = [f"# Striking distance report", ""]
    out.append(f"Generated {date.today().isoformat()} by gsc-striking-distance. "
               f"Striking distance = average position {args.min_pos:g}–{args.max_pos:g}; "
               f"potential clicks assume a move to position {args.target} at a benchmark CTR "
               f"of {expected_ctr(args.target):.0%}.")
    out.append("")

    if chart:
        first, last, total = trend(chart)
        change = (last["impr"] - first["impr"]) / first["impr"] if first["impr"] else 0
        out += ["## Summary", "",
                md_table(["Period", "Clicks", "Impressions", "Avg. position"], [
                    [f"Whole export ({total['from']} to {total['to']})", total["clicks"], f"{total['impr']:,}", f"{total['position']:.1f}"],
                    [f"First 4 weeks ({first['from']} to {first['to']})", first["clicks"], f"{first['impr']:,}", f"{first['position']:.1f}"],
                    [f"Last 4 weeks ({last['from']} to {last['to']})", last["clicks"], f"{last['impr']:,}", f"{last['position']:.1f}"],
                ]), "",
                f"Impressions changed {change:+.0%} between the first and last four weeks. "
                f"Overall CTR is {total['clicks'] / total['impr']:.2%}." if total["impr"] else "", ""]

    if pages:
        sd = striking_distance(pages, args.min_pos, args.max_pos, args.min_impr, args.target)
        out += ["## Pages in striking distance", "",
                f"{len(sd)} pages rank between {args.min_pos:g} and {args.max_pos:g} with at least "
                f"{args.min_impr} impressions. Ranked by clicks you could gain.", ""]
        if sd:
            out.append(md_table(["Page", "Impr.", "Clicks", "Position", "Potential clicks"],
                                [[short(path_only(r["key"]), 60), r["impressions"], r["clicks"],
                                  f"{r['position']:.1f}", f"+{r['gain']:.0f}"] for r in sd[: args.top]]))
            out.append("")
        out += ["### What to do with these", "",
                "- Rewrite the title and meta description so the result earns the click.",
                "- Put the direct answer to the query in the first paragraph.",
                "- Link to these pages from your stronger pages with descriptive anchor text.",
                "- Compare against the pages ranking above you and cover what they cover.", ""]

    if queries:
        sdq = striking_distance(queries, args.min_pos, args.max_pos, args.min_impr_query, args.target)
        q_impr = sum(q["impressions"] for q in queries)
        chart_impr = int(sum(num(r.get("Impressions")) for r in chart)) if chart else 0
        coverage = (f" Search Console hides rare queries for privacy, so this export's query table covers "
                    f"{q_impr:,} of {chart_impr:,} impressions ({q_impr / chart_impr:.0%}). "
                    "The page tables above are more complete." if chart_impr else "")
        out += ["## Queries in striking distance", "",
                f"{len(sdq)} queries rank between {args.min_pos:g} and {args.max_pos:g} with at least "
                f"{args.min_impr_query} impressions.{coverage}", ""]
        if sdq:
            out.append(md_table(["Query", "Impr.", "Clicks", "Position", "Potential clicks"],
                                [[short(r["key"]), r["impressions"], r["clicks"], f"{r['position']:.1f}",
                                  f"+{r['gain']:.0f}"] for r in sdq[: args.top]]))
            out.append("")

    if pages:
        lc = low_ctr(pages, 10, args.min_impr)
        out += ["## Page-one pages with weak click-through", "",
                "Already in the top 10, but getting less than half the benchmark CTR for their position. "
                "Usually a title or snippet problem, or an AI Overview answering the question first.", ""]
        if lc:
            out.append(md_table(["Page", "Impr.", "CTR", "Benchmark", "Position"],
                                [[short(path_only(r["key"]), 60), r["impressions"], f"{r['ctr']:.1%}",
                                  f"{r['expected']:.1%}", f"{r['position']:.1f}"] for r in lc[: args.top]]))
        else:
            out.append("None found.")
        out.append("")

        groups = group_pages(pages)
        out += ["## Where impressions come from", "",
                md_table(["Section", "Pages", "Impressions", "Share", "Clicks", "Avg. position"],
                         [[g["group"], g["pages"], f"{g['impressions']:,}", f"{g['share']:.0%}", g["clicks"],
                           f"{g['position']:.1f}"] for g in groups[:10]]), ""]

    if queries:
        long_q = [q for q in queries if len(q["key"].split()) > LONG_QUERY_WORDS]
        if long_q:
            impr = sum(q["impressions"] for q in long_q)
            out += ["## Machine-like queries", "",
                    f"{len(long_q)} queries are longer than {LONG_QUERY_WORDS} words ({impr:,} impressions). "
                    "Real people rarely type these. They look like prompts from AI tools or agents searching "
                    "on someone's behalf. Don't optimize for them, but it's a sign AI assistants are finding "
                    "your pages.", "",
                    md_table(["Query (start)", "Words", "Impr.", "Position"],
                             [[short(q["key"], 60), len(q["key"].split()), q["impressions"], f"{q['position']:.1f}"]
                              for q in sorted(long_q, key=lambda q: -q["impressions"])[:5]]), ""]

    out += ["---", "",
            "CTR benchmarks are rough industry ballparks, not your site's data. "
            "Treat potential clicks as a way to rank priorities, not a forecast.", ""]
    return "\n".join(out)


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})


def main():
    ap = argparse.ArgumentParser(description="Find Search Console pages and queries close to page one.")
    ap.add_argument("export", help="GSC Performance export: the .zip or an unzipped folder")
    ap.add_argument("--out", default="striking-distance-report.md", help="Markdown report path")
    ap.add_argument("--csv", metavar="DIR", help="also write striking-distance pages/queries as CSV to DIR")
    ap.add_argument("--min-pos", type=float, default=8, help="lowest average position to include (default 8)")
    ap.add_argument("--max-pos", type=float, default=20, help="highest average position to include (default 20)")
    ap.add_argument("--min-impr", type=int, default=20, help="minimum impressions for a page (default 20)")
    ap.add_argument("--min-impr-query", type=int, default=3, help="minimum impressions for a query (default 3)")
    ap.add_argument("--target", type=int, default=3, help="position used to estimate potential clicks (default 3)")
    ap.add_argument("--top", type=int, default=15, help="rows per table (default 15)")
    args = ap.parse_args()

    tables = read_export(args.export)
    if not any(k in tables for k in ("queries.csv", "pages.csv")):
        sys.exit("No Queries.csv or Pages.csv found. Export from Search Console > Performance > Export.")
    sample = (tables.get("pages.csv") or tables.get("queries.csv") or [{}])[0]
    if "Position" not in sample:
        sys.exit("This export has no Position column (the Generative AI features report doesn't include one). "
                 "Use the standard Search results export.")

    report = build_report(tables, args)
    Path(args.out).write_text(report, encoding="utf-8")
    print(f"Wrote {args.out}")

    if args.csv:
        d = Path(args.csv)
        d.mkdir(parents=True, exist_ok=True)
        fields = ["key", "impressions", "clicks", "ctr", "position", "gain"]
        for name, header, min_impr in (("pages", "Top pages", args.min_impr),
                                        ("queries", "Top queries", args.min_impr_query)):
            rows = normalize(tables.get(f"{name}.csv", []), header)
            sd = striking_distance(rows, args.min_pos, args.max_pos, min_impr, args.target)
            write_csv(d / f"striking-{name}.csv", sd, fields)
            print(f"Wrote {d / f'striking-{name}.csv'} ({len(sd)} rows)")


if __name__ == "__main__":
    main()
