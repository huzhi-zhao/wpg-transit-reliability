#!/usr/bin/env bash
# P0 window A: download the recent on-time table (gp3k-am4u) one service day at a time.
# The one-shot CSV export drops the connection after a few minutes, so page by day instead.
# Usage: probe/fetch_recent.sh [first_day] [last_day]   (defaults: 2026-10-10 2026-11-23)
# Output: data/raw/recent/YYYY-MM-DD.csv, plus data/raw/recent/_counts.tsv
#         (day, rows the API reports, rows written) so truncation is visible.
set -euo pipefail

first=${1:-2026-10-10}
last=${2:-2026-11-23}
out=data/raw/recent
api=https://data.winnipeg.ca/resource/gp3k-am4u
mkdir -p "$out"
: > "$out/_counts.tsv"

d=$first
while [[ "$d" < "$last" || "$d" == "$last" ]]; do
  where="scheduled_time%20between%20'${d}T00:00:00'%20and%20'${d}T23:59:59'"
  expected=$(curl -sf "$api.json?\$select=count(*)&\$where=$where" | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["count"])')
  curl -sf -o "$out/$d.csv" \
    "$api.csv?\$select=row_id,stop_number,route_number,route_destination,day_type,scheduled_time,deviation,location&\$where=$where&\$order=row_id&\$limit=1000000"
  got=$(( $(wc -l < "$out/$d.csv") - 1 ))
  printf '%s\t%s\t%s\n' "$d" "$expected" "$got" | tee -a "$out/_counts.tsv"
  d=$(date -j -v+1d -f %Y-%m-%d "$d" +%Y-%m-%d)
done
