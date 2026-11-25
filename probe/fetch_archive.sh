#!/usr/bin/env bash
# P0 window B: download monthly on-time archive zips (cymk-nyei) for a range of months.
# Usage: probe/fetch_archive.sh [first_month] [last_month]   (defaults: 2025-12-01 2026-03-01)
# Output: data/raw/archive/on_time_performance_YYYY_MM.zip, plus _counts.tsv
#         (month, rows the portal reports, rows in the CSV inside the zip).
set -euo pipefail

first=${1:-2025-12-01}
last=${2:-2026-03-01}
out=data/raw/archive
mkdir -p "$out"
: > "$out/_counts.tsv"

curl -sf "https://data.winnipeg.ca/resource/cymk-nyei.json?\$select=start_date,rows,url&\$where=start_date%3E='${first}'%20or%20start_date='${first}T00:00:00'&\$order=start_date&\$limit=200" |
python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if r['start_date'][:10] <= '$last':
        print(r['start_date'][:7], r['rows'], r['url'])
" | while read -r month rows url; do
  f="$out/$(basename "$url")"
  [[ -s "$f" ]] || curl -sfL -o "$f" "$url"
  got=$(( $(unzip -p "$f" | wc -l) - 1 ))
  printf '%s\t%s\t%s\n' "$month" "$rows" "$got" | tee -a "$out/_counts.tsv"
done
