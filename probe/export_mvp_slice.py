# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["duckdb>=1.1", "pandas>=2.2"]
# ///
"""Export the MVP data slice: route 91 toward St. Norbert, weekdays, scheduled before 18:00.

The archive parquet files have no route_destination column. Each archive row gets its destination
by joining on (stop, time of day HH:MM:SS) against the distinct (stop, time, destination) set in the
recent CSVs. Route 91's timetable did not change in 2025-07 .. 2026-11, and no key maps to two
destinations (the script checks this). Stop locations also come from the recent CSVs.

Inputs : data/raw/archive/parquet/*.parquet  (probe/fetch_archive.sh; columns route, stop_id, day_type, ts, dev)
         data/raw/recent/*.csv               (probe/fetch_recent.sh)
Run    : uv run probe/export_mvp_slice.py
Output : data/mvp/route91_st_norbert.csv
         columns route_number, route_destination, stop_number, day_type, scheduled_time, deviation, location
"""

from __future__ import annotations

import pathlib
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
OUT = ROOT / "data/mvp/route91_st_norbert.csv"
ROUTE, DEST, MAX_HOUR = "91", "St. Norbert", 18

con = duckdb.connect()
recent = str(RAW / "recent/2*.csv")
archive = str(RAW / "archive/parquet/*.parquet")

con.execute(f"""
CREATE TABLE rec AS
SELECT route_number, route_destination, stop_number, day_type,
       CAST(scheduled_time AS TIMESTAMP) AS scheduled_time,
       CAST(deviation AS INTEGER) AS deviation, location
FROM read_csv('{recent}', all_varchar=true)
WHERE route_number = '{ROUTE}'
""")

# (stop, time of day) -> destination, from the recent table
con.execute("""
CREATE TABLE keymap AS
SELECT DISTINCT stop_number, strftime(scheduled_time, '%H:%M:%S') AS tod, route_destination
FROM rec
""")
ambiguous = con.execute(
    "SELECT count(*) FROM (SELECT stop_number, tod FROM keymap GROUP BY ALL HAVING count(*) > 1)"
).fetchone()[0]
if ambiguous:
    sys.exit(f"{ambiguous} (stop, time) keys map to more than one destination; the join is not safe")

con.execute("""
CREATE TABLE loc AS
SELECT stop_number, any_value(location) AS location FROM rec GROUP BY stop_number
""")

con.execute(f"""
CREATE TABLE arc AS
SELECT a.route AS route_number, k.route_destination, a.stop_id AS stop_number, a.day_type,
       a.ts AS scheduled_time, a.dev AS deviation, l.location
FROM read_parquet('{archive}') a
LEFT JOIN keymap k ON k.stop_number = a.stop_id AND k.tod = strftime(a.ts, '%H:%M:%S')
LEFT JOIN loc l ON l.stop_number = a.stop_id
WHERE a.route = '{ROUTE}'
""")
unmapped = con.execute("SELECT count(*) FROM arc WHERE route_destination IS NULL").fetchone()[0]
print(f"archive rows of route {ROUTE} with no destination match: {unmapped:,}")

con.execute(f"""
CREATE TABLE slice AS
SELECT * FROM (SELECT * FROM arc UNION ALL SELECT * FROM rec)
WHERE route_destination = '{DEST}' AND day_type = 'Weekday' AND hour(scheduled_time) < {MAX_HOUR}
ORDER BY scheduled_time, stop_number
""")
n, stops, first, last, nulloc = con.execute(
    "SELECT count(*), count(DISTINCT stop_number), min(scheduled_time), max(scheduled_time), "
    "count(*) FILTER (WHERE location IS NULL) FROM slice"
).fetchone()

OUT.parent.mkdir(parents=True, exist_ok=True)
con.execute(f"COPY slice TO '{OUT}' (HEADER, DELIMITER ',', TIMESTAMPFORMAT '%Y-%m-%d %H:%M:%S')")
print(f"rows {n:,}  stops {stops}  first {first}  last {last}  rows without location {nulloc}")
print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.1f} MB)")
