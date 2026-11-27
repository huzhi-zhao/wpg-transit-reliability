# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["duckdb>=1.1", "pandas>=2.2"]
# ///
"""Per-route data quality after the 2025-07 network redesign, used to pick the MVP slice (ADR 0007).

Inputs : data/raw/archive/parquet/*.parquet  (written by probe/window_b.py)
         data/raw/recent/*.csv               (probe/fetch_recent.sh)
Scope  : Day Type = Weekday, scheduled before 18:00
Run    : uv run probe/route_quality.py
Output : printed tables
"""

from __future__ import annotations

import pathlib

import duckdb

RAW = pathlib.Path(__file__).resolve().parents[1] / "data/raw"
STABLE_SPAN = 300  # a departure "survives" if it is seen across >= 300 real weekdays

c = duckdb.connect()
c.sql(f"""
CREATE TABLE raw AS
SELECT route, stop_id, day_type, ts, dev FROM '{RAW}/archive/parquet/*.parquet'
UNION ALL
SELECT route_number, CAST(stop_number AS VARCHAR), day_type, scheduled_time, deviation
FROM read_csv_auto('{RAW}/recent/*.csv')
""")
# Real weekdays: Mon-Fri dates where most rows say Weekday (holidays run as Sunday/Holiday;
# weekend dates carry a few stray Weekday rows).
c.sql("""
CREATE TABLE wd AS
SELECT CAST(ts AS DATE) d FROM raw GROUP BY 1
HAVING avg((day_type = 'Weekday')::INT) > 0.5 AND dayofweek(CAST(ts AS DATE)) BETWEEN 1 AND 5
""")
print("real weekdays:", c.sql("SELECT count(*), min(d), max(d) FROM wd").fetchall())

c.sql("""
CREATE TABLE f AS
SELECT route, stop_id, CAST(ts AS DATE) d, strftime(ts, '%H:%M:%S') t, dev
FROM raw WHERE day_type = 'Weekday' AND hour(ts) < 18 AND CAST(ts AS DATE) IN (SELECT d FROM wd)
""")
c.sql("""
CREATE TABLE k0 AS
SELECT route, stop_id, t, count(*) n, count(DISTINCT d) nd, min(d) d0, max(d) d1,
       count(*) FILTER (WHERE abs(dev) > 3600) nout
FROM f GROUP BY route, stop_id, t
""")
c.sql("""
CREATE TABLE k AS
SELECT k0.*, (SELECT count(*) FROM wd WHERE wd.d BETWEEN k0.d0 AND k0.d1) span FROM k0
""")
print(c.sql(f"""
WITH rd AS (SELECT route, count(DISTINCT d) n_days FROM f GROUP BY 1)
SELECT route, sum(n) n_rows,
       round(100.0 * sum(nout) / sum(n), 3) pct_abs_dev_gt_3600,
       round(100.0 * sum(n - nd) / sum(n), 3) pct_dup,
       round(100.0 * sum(n) FILTER (WHERE span >= {STABLE_SPAN}) / sum(n), 1) pct_rows_stable,
       any_value(n_days) days_with_data
FROM k JOIN rd USING (route)
GROUP BY route HAVING sum(n) > 50000
ORDER BY pct_rows_stable DESC, n_rows DESC
""").df().to_string())

# Candidate slices: direction is recovered from the recent table (keys are unambiguous for these routes).
c.sql("""
CREATE TABLE dirmap AS
SELECT DISTINCT route_number route, CAST(stop_number AS VARCHAR) stop_id,
       strftime(scheduled_time, '%H:%M:%S') t, route_destination dest
FROM read_csv_auto('""" + str(RAW) + """/recent/*.csv') WHERE route_number IN ('91', '642')
""")
print(c.sql("""
SELECT route, dest, count(*) n_rows, count(DISTINCT stop_id) stops,
       round(avg((dev < -300)::INT), 4) late_300s, round(avg((dev > 60)::INT), 4) early_60s,
       round(avg((dev < -300)::INT) FILTER (WHERE month(d) IN (12, 1, 2, 3)), 4) late_300s_winter,
       round(avg((dev < -300)::INT) FILTER (WHERE month(d) NOT IN (12, 1, 2, 3)), 4) late_300s_other
FROM f JOIN dirmap USING (route, stop_id, t)
WHERE abs(dev) <= 3600
GROUP BY ALL ORDER BY 1, 2
""").df().to_string())
