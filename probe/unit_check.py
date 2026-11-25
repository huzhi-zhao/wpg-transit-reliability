# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["duckdb>=1.1", "pandas>=2.2"]
# ///
"""Check the MVP prediction unit of ADR 0005 on window A (record only, added 2026-11-25).

Unit: (Route Number, Route Destination, Stop Number, time of day of Scheduled Time), weekdays before 18:00.
Questions: is it unique within a day; does it recur across the weekdays of one timetable period;
does it map to exactly one GTFS (trip, stop).
Inputs : data/raw/recent/*.csv (probe/fetch_recent.sh), data/raw/gtfs/ (current GTFS)
Run    : uv run probe/unit_check.py
"""

import pathlib

import duckdb
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
counts = pd.read_csv(RAW / "recent/_counts.tsv", sep="\t", names=["day", "e", "g"], dtype=str)
files = [str(RAW / f"recent/{d}.csv") for d in counts[counts.e == counts.g].day]
con = duckdb.connect()
q = lambda s: con.execute(s).df()  # noqa: E731
con.execute(f"""CREATE TABLE r AS SELECT route_number route, route_destination dest, stop_number stop,
  CAST(scheduled_time AS TIMESTAMP) ts FROM read_csv({files}, all_varchar=true)
  WHERE day_type='Weekday' AND hour(CAST(scheduled_time AS TIMESTAMP)) < 18
    AND CAST(CAST(scheduled_time AS TIMESTAMP) AS DATE) NOT IN (DATE '2026-10-12', DATE '2026-11-11')
    AND dayofweek(CAST(scheduled_time AS TIMESTAMP)) BETWEEN 1 AND 5""")
con.execute("CREATE TABLE u AS SELECT route, dest, stop, strftime(ts, '%H:%M:%S') hms, CAST(ts AS DATE) d FROM r")

n_days = q("SELECT count(DISTINCT d) n FROM u").n[0]
dup = q("""SELECT count(*) n, sum(c) FILTER (WHERE c > 1) dup_rows FROM
           (SELECT route, dest, stop, hms, d, count(*) c FROM u GROUP BY ALL)""").iloc[0]
print(f"weekdays {n_days}; unit-days {dup.n:,}; records in a unit-day with more than one record: "
      f"{(dup.dup_rows or 0):,} ({(dup.dup_rows or 0)/dup.n:.2%} of unit-days' worth)")

rec = q("SELECT route, dest, stop, hms, count(DISTINCT d) k FROM u GROUP BY ALL")
print(f"distinct units {len(rec):,}; days observed per unit: "
      + ", ".join(f"P{p}={rec.k.quantile(p/100):.0f}" for p in (10, 25, 50, 75, 90))
      + f"; seen on 1 day only {(rec.k == 1).mean():.1%}; >= 10 days {(rec.k >= 10).mean():.1%}")

# Map units to GTFS (trip, stop) with the current timetable; destination is not in GTFS, so route+stop+time.
g = RAW / "gtfs"
con.execute(f"""CREATE TABLE st AS SELECT s.trip_id, s.stop_id, s.departure_time hms, r.route_short_name route
  FROM read_csv('{g}/stop_times.txt', all_varchar=true) s
  JOIN read_csv('{g}/trips.txt', all_varchar=true) t USING (trip_id)
  JOIN read_csv('{g}/routes.txt', all_varchar=true) r USING (route_id)
  JOIN read_csv('{g}/calendar.txt', all_varchar=true) c USING (service_id)
  WHERE c.monday='1' AND c.saturday='0' AND c.sunday='0'""")
mp = q("""SELECT n_trip, count(*) units FROM (
            SELECT u.route, u.dest, u.stop, u.hms, count(DISTINCT st.trip_id) n_trip
            FROM (SELECT DISTINCT route, dest, stop, hms FROM u) u
            LEFT JOIN st ON st.route=u.route AND st.stop_id=u.stop AND st.hms=u.hms GROUP BY ALL)
          GROUP BY n_trip ORDER BY n_trip""")
tot = mp.units.sum()
print("GTFS weekday (trip, stop) matches per unit: " + ", ".join(f"{int(r.n_trip)} -> {r.units/tot:.2%}" for r in mp.itertuples()))
dd = q("SELECT route, stop, hms, count(DISTINCT dest) nd FROM (SELECT DISTINCT route, dest, stop, hms FROM u) GROUP BY ALL")
print(f"(route, stop, time) keys carried by more than one destination: {(dd.nd > 1).mean():.2%}")
