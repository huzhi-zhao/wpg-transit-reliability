# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["duckdb>=1.1", "pandas>=2.2", "numpy>=1.26", "statsmodels>=0.14", "scipy>=1.11"]
# ///
"""P0 window A probe: G1 coverage, G2b time bands, G2c block clustering, I1, I2 (between-trip), I3.

Design: docs/dev/design/20261124-feasibility-probe.md
Inputs : data/raw/recent/*.csv  (probe/fetch_recent.sh)
         data/raw/gtfs/          (current GTFS, valid 2026-09-06 .. 2026-12-12)
Run    : uv run probe/window_a.py
Output : printed report + data/out/window_a.json
"""

from __future__ import annotations

import json
import pathlib
import sys

import duckdb
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
OUT = ROOT / "data/out"
FIRST, LAST = "2026-10-10", "2026-11-23"
LATE_S = 300  # I2 event: late by more than 300 s (deviation < -300)
CITY_BBOX = (-97.40, -96.90, 49.70, 50.05)  # lon_min, lon_max, lat_min, lat_max (generous)
BANDS = [(0, 6, "<6 (not in G2b)"), (6, 9, "06-09"), (9, 15, "09-15"), (15, 18, "15-18"), (18, 99, "18+")]

con = duckdb.connect()
q = lambda sql: con.execute(sql).df()  # noqa: E731
res: dict = {"window": [FIRST, LAST]}


def section(title: str) -> None:
    print(f"\n=== {title}")


# ---------------------------------------------------------------- load
# Only days whose row count matches what the API reported (probe/fetch_recent.sh writes _counts.tsv).
counts = pd.read_csv(RAW / "recent/_counts.tsv", sep="\t", names=["day", "expected", "got"], dtype=str)
ok = counts[counts.expected == counts.got].day.tolist()
bad = counts[counts.expected != counts.got].day.tolist()
if bad:
    print("days skipped, row count mismatch:", bad)
FILES = "[" + ",".join(f"'{RAW}/recent/{d}.csv'" for d in ok) + "]"
LAST = min(LAST, max(ok))
con.execute(f"""
CREATE TABLE rec AS
SELECT CAST(row_id AS BIGINT) row_id,
       CAST(stop_number AS VARCHAR) stop_id,
       CAST(route_number AS VARCHAR) route,
       day_type,
       CAST(scheduled_time AS TIMESTAMP) ts,
       CAST(deviation AS INTEGER) dev,
       TRY_CAST(regexp_extract(location, 'POINT \\(([-0-9.]+) ', 1) AS DOUBLE) lon,
       TRY_CAST(regexp_extract(location, ' ([-0-9.]+)\\)', 1) AS DOUBLE) lat
FROM read_csv({FILES}, all_varchar=true, header=true)
""")
g = f"{RAW}/gtfs"
con.execute(f"CREATE TABLE trips AS SELECT * FROM read_csv('{g}/trips.txt', all_varchar=true)")
con.execute(f"CREATE TABLE routes AS SELECT * FROM read_csv('{g}/routes.txt', all_varchar=true)")
con.execute(f"""
CREATE TABLE st AS
SELECT trip_id, stop_id, CAST(stop_sequence AS INTEGER) seq,
       CAST(split_part(departure_time,':',1) AS INTEGER)*3600
     + CAST(split_part(departure_time,':',2) AS INTEGER)*60
     + CAST(split_part(departure_time,':',3) AS INTEGER) dep_s,
       CAST(split_part(arrival_time,':',1) AS INTEGER)*3600
     + CAST(split_part(arrival_time,':',2) AS INTEGER)*60
     + CAST(split_part(arrival_time,':',3) AS INTEGER) arr_s
FROM read_csv('{g}/stop_times.txt', all_varchar=true)
""")
con.execute(f"CREATE TABLE cal AS SELECT * FROM read_csv('{g}/calendar.txt', all_varchar=true)")
con.execute(f"CREATE TABLE cald AS SELECT * FROM read_csv('{g}/calendar_dates.txt', all_varchar=true)")

# Active (service_date, service_id) over the window: calendar weekday flags, then calendar_dates exceptions.
con.execute(f"""
CREATE TABLE active AS
WITH days AS (SELECT CAST(d AS DATE) d FROM range(DATE '{FIRST}' - INTERVAL 1 DAY, DATE '{LAST}' + INTERVAL 1 DAY, INTERVAL 1 DAY) t(d)),
base AS (
  SELECT days.d, cal.service_id FROM days, cal
  WHERE days.d BETWEEN strptime(cal.start_date,'%Y%m%d') AND strptime(cal.end_date,'%Y%m%d')
    AND CASE dayofweek(days.d) WHEN 0 THEN cal.sunday WHEN 1 THEN cal.monday WHEN 2 THEN cal.tuesday
        WHEN 3 THEN cal.wednesday WHEN 4 THEN cal.thursday WHEN 5 THEN cal.friday ELSE cal.saturday END = '1'),
ex AS (SELECT CAST(strptime(date,'%Y%m%d') AS DATE) d, service_id, exception_type FROM cald)
SELECT d, service_id FROM base
WHERE NOT EXISTS (SELECT 1 FROM ex WHERE ex.d=base.d AND ex.service_id=base.service_id AND exception_type='2')
UNION
SELECT d, service_id FROM ex WHERE exception_type='1'
""")
# Weekday service days = days on which the weekday service (Mon-Fri pattern) runs.
wk_sid = q("SELECT service_id FROM cal WHERE monday='1' AND friday='1' AND saturday='0' AND sunday='0'").service_id.tolist()
assert len(wk_sid) == 1, wk_sid
WK = wk_sid[0]
con.execute(f"CREATE TABLE wdays AS SELECT d FROM active WHERE service_id='{WK}' AND d BETWEEN DATE '{FIRST}' AND DATE '{LAST}'")

sched = q(f"""SELECT count(*) n FROM wdays""").n[0]
res["weekday_service_days"] = int(sched)

section("Load")
tot = q("SELECT count(*) n, min(ts) a, max(ts) b, count(DISTINCT route) r FROM rec").iloc[0]
print(f"records {tot.n:,}  {tot.a} .. {tot.b}  routes {tot.r}   weekday service days {sched}")
res["records_total"] = int(tot.n)

# ---------------------------------------------------------------- join
# Each record has two candidate (service_date, seconds) keys: same calendar day, or previous service day past 24:00.
con.execute(f"""
CREATE TABLE cand AS
SELECT row_id, stop_id, route, dev, CAST(ts AS DATE) sd,
       hour(ts)*3600+minute(ts)*60+second(ts) s FROM rec WHERE day_type='Weekday'
UNION ALL
SELECT row_id, stop_id, route, dev, CAST(ts AS DATE) - 1 sd,
       hour(ts)*3600+minute(ts)*60+second(ts) + 86400 s FROM rec WHERE day_type='Weekday' AND hour(ts) < 6
""")
con.execute(f"""
CREATE TABLE m AS
SELECT c.row_id, c.sd, c.dev, st.trip_id, st.seq, t.block_id
FROM cand c
JOIN st ON st.stop_id=c.stop_id AND st.dep_s=c.s
JOIN trips t ON t.trip_id=st.trip_id
JOIN routes r ON r.route_id=t.route_id AND r.route_short_name=c.route
JOIN active a ON a.d=c.sd AND a.service_id=t.service_id
WHERE t.service_id='{WK}' AND c.sd IN (SELECT d FROM wdays)
""")
j = q("""
WITH wk AS (SELECT row_id FROM rec WHERE day_type='Weekday' AND CAST(ts AS DATE) IN (SELECT d FROM wdays)),
per AS (SELECT row_id, count(*) k FROM m GROUP BY row_id)
SELECT (SELECT count(*) FROM wk) n,
       count(*) FILTER (WHERE per.k=1) one,
       count(*) FILTER (WHERE per.k>1) many
FROM wk LEFT JOIN per USING(row_id)
""").iloc[0]
section("Join (window A, weekday service days, records with Day Type=Weekday)")
print(f"weekday records {j.n:,}; matched exactly once {j.one:,} ({j.one/j.n:.2%}); ambiguous {j.many:,} ({j.many/j.n:.2%}); "
      f"unmatched {(j.n-j.one-j.many):,} ({(j.n-j.one-j.many)/j.n:.2%})")
res["join"] = {"weekday_records": int(j.n), "matched_once": int(j.one), "ambiguous": int(j.many)}
um = q("""
WITH wk AS (SELECT * FROM rec WHERE day_type='Weekday' AND CAST(ts AS DATE) IN (SELECT d FROM wdays))
SELECT route, count(*) n FROM wk WHERE row_id NOT IN (SELECT row_id FROM m) GROUP BY route ORDER BY n DESC LIMIT 8""")
print("unmatched by route (top):", dict(zip(um.route, um.n)))

# Observations: one per (service day, trip, stop). Ambiguous records dropped; duplicates keep the lowest row_id.
con.execute("""
CREATE TABLE obs AS
SELECT sd, trip_id, seq, block_id, arg_min(dev, row_id) dev
FROM m WHERE row_id IN (SELECT row_id FROM m GROUP BY row_id HAVING count(*)=1)
GROUP BY sd, trip_id, seq, block_id
""")

# ---------------------------------------------------------------- G1
con.execute(f"""
CREATE TABLE tsched AS
WITH tm AS (SELECT trip_id, min(dep_s) first_s, count(*) n_stops FROM st GROUP BY trip_id)
SELECT w.d sd, t.trip_id, r.route_short_name route, t.block_id, tm.first_s, tm.n_stops
FROM wdays w CROSS JOIN trips t JOIN routes r ON r.route_id=t.route_id JOIN tm ON tm.trip_id=t.trip_id
WHERE t.service_id='{WK}'
""")
con.execute("""
CREATE TABLE tcov AS
SELECT s.*, o.k IS NOT NULL present, coalesce(o.k,0) k_obs
FROM tsched s LEFT JOIN (SELECT sd, trip_id, count(*) k FROM obs GROUP BY sd, trip_id) o USING(sd, trip_id)
""")
dr = q("""SELECT route, sd, avg(present::INT) cov,
                 avg(CASE WHEN present THEN k_obs/n_stops END) compl, count(*) n_trips
          FROM tcov GROUP BY route, sd""")
per_route = dr.groupby("route").agg(cov_med=("cov", "median"), compl_med=("compl", "median"),
                                    trips_per_day=("n_trips", "median")).sort_values("cov_med", ascending=False)
net = q("SELECT avg(present::INT) c FROM tcov").c[0]
qual = per_route[(per_route.cov_med >= 0.30) & (per_route.compl_med >= 0.90)]
section("G1 trip coverage (gate: >=3 routes with median weekday coverage >=30% and completeness >=90%)")
print(f"network pooled coverage {net:.1%}; routes {len(per_route)}; routes meeting both {len(qual)}")
print("coverage distribution across routes (median per route): "
      + ", ".join(f"P{p}={per_route.cov_med.quantile(p/100):.1%}" for p in (10, 25, 50, 75, 90)))
print(per_route.head(12).to_string(float_format=lambda x: f"{x:.3f}"))
if "D19" in per_route.index:
    print("D19:", per_route.loc["D19"].round(3).to_dict())
res["G1"] = {"network_coverage": net, "routes": len(per_route), "routes_qualifying": len(qual),
             "qualifying": qual.round(4).reset_index().to_dict("records"),
             "route_cov_quantiles": {p: per_route.cov_med.quantile(p / 100) for p in (10, 25, 50, 75, 90)},
             "D19": per_route.loc["D19"].to_dict() if "D19" in per_route.index else None,
             "pass": bool(len(qual) >= 3)}

# daily network coverage, to see whether whole days drop out
daily = q("SELECT sd, avg(present::INT) cv FROM tcov GROUP BY sd ORDER BY sd")
print("daily network coverage: min {:.1%} median {:.1%} max {:.1%}".format(daily.cv.min(), daily.cv.median(), daily.cv.max()))
res["daily_cov"] = {str(r.sd.date()) if hasattr(r.sd, "date") else str(r.sd): r.cv for r in daily.itertuples()}

# ---------------------------------------------------------------- G2b
t = q("SELECT first_s, present FROM tcov")
t["h"] = t.first_s // 3600
bands = []
for lo, hi, name in BANDS:
    sub = t[(t.h >= lo) & (t.h < hi)]
    bands.append((name, sub.present.mean(), len(sub)))
four = [b[1] for b in bands[1:]]
section("G2b coverage by time band of trip start (gate: range of the four bands < 15 pp)")
for name, c, n in bands:
    print(f"  {name:16s} {c:.1%}  (trip-days {n:,})")
rng = max(four) - min(four)
print(f"range of four bands: {rng*100:.1f} pp")
res["G2b"] = {"bands": {n: c for n, c, _ in bands}, "range_pp": rng * 100, "pass": bool(rng < 0.15)}
# Detail (record only): by start hour, and whether the evening gap is network-wide or a few routes.
byh = t.groupby("h").present.agg(["mean", "size"])
print("  by start hour: " + "  ".join(f"{h:02d}:{r['mean']:.0%}" for h, r in byh.iterrows() if r["size"] >= 200))
rb = q("""SELECT route, avg(present::INT) FILTER (WHERE first_s < 18*3600) day_cov,
                 avg(present::INT) FILTER (WHERE first_s >= 18*3600) eve_cov FROM tcov GROUP BY route""").dropna()
rb["gap"] = rb.day_cov - rb.eve_cov
print(f"  routes with evening trips: {len(rb)}; day-minus-evening coverage gap per route "
      + ", ".join(f"P{p}={rb.gap.quantile(p/100)*100:.0f}pp" for p in (10, 50, 90))
      + f"; routes with evening coverage < 10%: {(rb.eve_cov < 0.10).sum()}")
res["G2b_detail"] = {"by_hour": byh["mean"].to_dict(), "route_gap_pp": {p: rb.gap.quantile(p / 100) * 100 for p in (10, 50, 90)},
                     "routes_evening_lt10": int((rb.eve_cov < 0.10).sum())}

# ---------------------------------------------------------------- G2c
blk = q("""SELECT sd, block_id, count(*) n, sum(present::INT) k FROM tcov GROUP BY sd, block_id HAVING count(*)>=2""")
dayp = q("SELECT sd, avg(present::INT) p FROM tcov GROUP BY sd")
blk = blk.merge(dayp, on="sd")
blk["all_or_none"] = (blk.k == 0) | (blk.k == blk.n)
blk["exp"] = blk.p ** blk.n + (1 - blk.p) ** blk.n
section("G2c block clustering (record only)")
print(f"block-days with >=2 trips: {len(blk):,}; all-or-none observed {blk.all_or_none.mean():.1%} "
      f"vs {blk.exp.mean():.1%} expected if trips went missing independently")
res["G2c"] = {"block_days": len(blk), "all_or_none_obs": blk.all_or_none.mean(), "all_or_none_exp_indep": blk.exp.mean()}

# ---------------------------------------------------------------- G2 follow-ups (record only, added after G2b failed)
EVE = 18 * 3600
section("G2 follow-up 1: does the evening gap come from which vehicles (blocks) run in the evening?")
bk = q(f"""
WITH b AS (SELECT sd, block_id, bool_or(first_s < {EVE}) has_day, bool_or(first_s >= {EVE}) has_eve FROM tcov GROUP BY sd, block_id)
SELECT CASE WHEN has_day AND has_eve THEN 'mixed' WHEN has_eve THEN 'evening-only' ELSE 'day-only' END kind,
       CASE WHEN t.first_s < {EVE} THEN 'day trips' ELSE 'evening trips' END part,
       avg(t.present::INT) cov, count(*) n
FROM tcov t JOIN b USING (sd, block_id) GROUP BY ALL ORDER BY kind, part""")
print(bk.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
agree = q(f"""
WITH s AS (SELECT sd, block_id,
             avg(present::INT) FILTER (WHERE first_s < {EVE}) dcov,
             avg(present::INT) FILTER (WHERE first_s >= {EVE}) ecov FROM tcov GROUP BY sd, block_id)
SELECT count(*) n, avg(((dcov > 0) = (ecov > 0))::INT) same_status FROM s WHERE dcov IS NOT NULL AND ecov IS NOT NULL""").iloc[0]
print(f"mixed block-days {agree.n:,}: day part and evening part both present or both absent in {agree.same_status:.1%}")
# Within mixed block-days whose daytime part is fully recorded: coverage of each later trip by start hour.
fh = q(f"""
WITH s AS (SELECT sd, block_id FROM tcov GROUP BY sd, block_id
           HAVING bool_or(first_s >= {EVE}) AND min(present::INT) FILTER (WHERE first_s < {EVE}) = 1)
SELECT t.first_s // 3600 h, avg(t.present::INT) cv, count(*) n FROM tcov t JOIN s USING (sd, block_id)
WHERE t.first_s >= 15*3600 GROUP BY 1 ORDER BY 1""")
print("block-days whose daytime trips were ALL recorded -> coverage of their trips by start hour: "
      + "  ".join(f"{int(r.h):02d}:{r.cv:.0%}(n={r.n})" for r in fh.itertuples()))
res["G2_followup_blocks_fullday_by_hour"] = {int(r.h): r.cv for r in fh.itertuples()}
res["G2_followup_blocks"] = {"table": bk.to_dict("records"), "mixed_block_days": int(agree.n), "same_status": agree.same_status}

section("G2 follow-up 2: on days a route loses more trips, do the recorded trips look less late? (trips starting before 18:00)")
# If late trips were the ones going missing, low-coverage route-days would show a LOWER observed late rate: positive slope.
rd = q(f"""
WITH c AS (SELECT route, sd, avg(present::INT) cv, count(*) n FROM tcov WHERE first_s < {EVE} GROUP BY route, sd),
l AS (SELECT s.route, o.sd, avg((o.dev < -{LATE_S})::INT) late FROM obs o
      JOIN (SELECT DISTINCT trip_id, route, first_s FROM tsched) s USING (trip_id)
      WHERE s.first_s < {EVE} GROUP BY s.route, o.sd)
SELECT c.*, l.late FROM c JOIN l USING (route, sd)""")


def demean(df: pd.DataFrame, cols: list[str], by: list[str], iters: int = 50) -> pd.DataFrame:
    out = df[cols].copy()
    for _ in range(iters):
        for b in by:
            out -= out.groupby(df[b]).transform("mean")
    return out


def slope(df: pd.DataFrame, by: list[str]) -> float:
    r = demean(df, ["cv", "late"], by)
    return float((r.cv * r.late).sum() / (r.cv ** 2).sum())


rng_ = np.random.default_rng(1)
days = rd.sd.unique()
for by, label in ((["route"], "within route"), (["route", "sd"], "within route and day")):
    b = slope(rd, by)
    boots = []
    for _ in range(300):
        pick = rng_.choice(days, len(days))
        bs = pd.concat([rd[rd.sd == d].assign(sd=f"{d}#{i}") for i, d in enumerate(pick)])
        boots.append(slope(bs, by))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"  {label:22s}: +10 pp coverage -> late rate {b*10:+.2f} pp  (95% CI {lo*10:+.2f} .. {hi*10:+.2f}, bootstrap over days)")
    res.setdefault("G2_followup_cov_late", {})[label] = {"per_10pp": b * 10, "ci": [lo * 10, hi * 10]}
print(f"  route-days {len(rd):,}; mean late rate {rd.late.mean():.1%}; SD of coverage within route {demean(rd, ['cv'], ['route']).cv.std():.3f}")

# ---------------------------------------------------------------- I1
section("I1 data quality (window A, all records)")
i1 = q(f"""
SELECT count(*) n,
  count(*) - count(DISTINCT (stop_id, route, ts)) dup,
  count(*) FILTER (WHERE abs(dev) > 3600) big,
  count(*) FILTER (WHERE lon IS NULL OR lat IS NULL) noloc,
  count(*) FILTER (WHERE lon NOT BETWEEN {CITY_BBOX[0]} AND {CITY_BBOX[1]} OR lat NOT BETWEEN {CITY_BBOX[2]} AND {CITY_BBOX[3]}) outside
FROM rec""").iloc[0]
for k in ("dup", "big", "noloc", "outside"):
    print(f"  {k:8s} {i1[k]:,} ({i1[k]/i1.n:.3%})")
res["I1"] = {k: int(i1[k]) for k in ("n", "dup", "big", "noloc", "outside")}

# ---------------------------------------------------------------- I3
section("I3 label validity (share of observations at terminal stops or scheduled dwell >= 120 s)")
i3 = q("""
WITH last AS (SELECT trip_id, max(seq) mx FROM st GROUP BY trip_id)
SELECT count(*) n,
  count(*) FILTER (WHERE o.seq = l.mx) terminal,
  count(*) FILTER (WHERE st.dep_s - st.arr_s >= 120) dwell
FROM obs o JOIN st ON st.trip_id=o.trip_id AND st.seq=o.seq JOIN last l ON l.trip_id=o.trip_id""").iloc[0]
print(f"  terminal {i3.terminal/i3.n:.2%}   dwell>=120s {i3.dwell/i3.n:.2%}   (observations {i3.n:,})")
res["I3"] = {k: int(i3[k]) for k in ("n", "terminal", "dwell")}

# ---------------------------------------------------------------- I2 between-trip
section(f"I2 between-trip spread (event: late > {LATE_S}s)")
cells = q(f"""SELECT trip_id, seq, count(*) n_days, avg((dev < -{LATE_S})::INT) rate FROM obs GROUP BY trip_id, seq""")
c10 = cells[cells.n_days >= 10]
overall = q(f"SELECT avg((dev < -{LATE_S})::INT) r, count(*) n FROM obs").iloc[0]
print(f"overall event rate {overall.r:.2%} over {overall.n:,} observations")
print(f"(trip, stop) cells with >=10 days: {len(c10):,} of {len(cells):,}")
res["I2_cells"] = {"overall_rate": overall.r, "cells_ge10": len(c10)}
if len(c10):
    print("  observed rate " + ", ".join(f"P{p}={c10.rate.quantile(p/100):.1%}" for p in (10, 50, 90)))
    # Spread expected from sampling noise alone if every cell had the overall rate.
    sim = np.random.default_rng(0).binomial(c10.n_days.values, overall.r) / c10.n_days.values
    print("  same quantiles under pure sampling noise: "
          + ", ".join(f"P{p}={np.quantile(sim, p/100):.1%}" for p in (10, 50, 90)))
    res["I2_cells"].update(obs={p: c10.rate.quantile(p / 100) for p in (10, 50, 90)},
                           noise_only={p: float(np.quantile(sim, p / 100)) for p in (10, 50, 90)})

# Variance decomposition. The design suggests a logistic GLMM; statsmodels' variational fit did not finish in
# 10 minutes on 250k rows, so use Henderson's Method I (moments, crossed random effects, unbalanced) instead.
# Unit: one trip on one service day; z = share of that trip's observed stops that were late > LATE_S.
# z_td = mu + a_trip + b_day + e_td ; e_td is "this trip on this day" (incl. causes we cannot see) plus stop noise.
z = q(f"SELECT trip_id, sd, avg((dev < -{LATE_S})::INT) z FROM obs GROUP BY trip_id, sd")
N = len(z)
T_t = z.groupby("trip_id").z.agg(["sum", "count"])
T_d = z.groupby("sd").z.agg(["sum", "count"])
R, D = len(T_t), len(T_d)
sA = (T_t["sum"] ** 2 / T_t["count"]).sum()
sB = (T_d["sum"] ** 2 / T_d["count"]).sum()
s0 = (z.z ** 2).sum()
cf = z.z.sum() ** 2 / N
kt = (T_t["count"] ** 2).sum() / N
kd = (T_d["count"] ** 2).sum() / N
A = np.array([[N - kt, R - kd, R - 1],
              [D - kt, N - kd, D - 1],
              [N - kt, N - kd, N - 1]], dtype=float)
var_trip, var_day, var_e = np.linalg.solve(A, np.array([sA - cf, sB - cf, s0 - cf]))
tot_v = var_trip + var_day + var_e
print(f"variance decomposition of trip-day late share ({N:,} trip-days, {R:,} trips, {D} days; Henderson I):")
print(f"  SD(trip) {np.sqrt(max(var_trip,0)):.3f}  SD(day) {np.sqrt(max(var_day,0)):.3f}  SD(trip x day) {np.sqrt(max(var_e,0)):.3f}")
print(f"  share: trip {var_trip/tot_v:.1%}  day {var_day/tot_v:.1%}  trip-x-day {var_e/tot_v:.1%}")
res["I2_decomp"] = {"method": "Henderson I on trip-day late share", "trip_days": N, "trips": R, "days": D,
                    "var_trip": var_trip, "var_day": var_day, "var_trip_x_day": var_e}

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "window_a.json").write_text(json.dumps(res, indent=1, default=float))
print(f"\nwrote {OUT/'window_a.json'}", file=sys.stderr)
