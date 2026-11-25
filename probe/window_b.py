# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["duckdb>=1.1", "pandas>=2.2", "numpy>=1.26"]
# ///
"""P0 window B probe: G3 (historical GTFS join rate by month), G2a (coverage on bad-weather days),
I2 weather difference and baseline Brier score with its decomposition.

Design: docs/dev/design/20261124-feasibility-probe.md ; scope per ADR 0004 (trips leaving their first stop before
18:00) for G2a and I2. G3 reports all weekday records and the before-18:00 subset.
Inputs : data/raw/archive/*.zip        (probe/fetch_archive.sh 2025-07-01 2026-09-01)
         data/raw/gtfs_hist/mdb-*/      (uv run probe/gtfs_history.py --download 2025-06-29 2026-12-12)
         data/out/weather_days.csv     (uv run probe/weather_days.py)
Run    : uv run probe/window_b.py
Output : printed report + data/out/window_b.json
"""

from __future__ import annotations

import json
import pathlib
import re
import zipfile

import duckdb
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/out"
EVE = 18 * 3600
LATE_S = 300
WIN_B = ("2025-12-01", "2026-03-31")
TRAIN, TEST = ("2025-12-01", "2026-02-28"), ("2026-03-01", "2026-03-31")

con = duckdb.connect()
con.execute("SET preserve_insertion_order=false")
q = lambda sql: con.execute(sql).df()  # noqa: E731
res: dict = {}


def section(t: str) -> None:
    print(f"\n=== {t}")


# ---------------------------------------------------------------- archive -> parquet (once)
pq_dir = RAW / "archive/parquet"
pq_dir.mkdir(exist_ok=True)
counts = pd.read_csv(RAW / "archive/_counts.tsv", sep="\t", names=["month", "expected", "got"], dtype=str)
months = counts[counts.expected == counts.got].month.tolist()
skipped = counts[counts.expected != counts.got].month.tolist()
if skipped:
    print("months skipped, row count mismatch:", skipped)
for m in months:
    pq = pq_dir / f"{m}.parquet"
    if pq.exists():
        continue
    z = RAW / f"archive/on_time_performance_{m.replace('-', '_')}.zip"
    tmp = RAW / "archive/_tmp.csv"
    with zipfile.ZipFile(z) as zf, open(tmp, "wb") as f:
        f.write(zf.read(zf.namelist()[0]))
    con.execute(f"""COPY (SELECT CAST("Row ID" AS BIGINT) row_id, CAST("Stop Number" AS VARCHAR) stop_id,
        CAST("Route Number" AS VARCHAR) route, "Day Type" day_type, CAST("Scheduled Time" AS TIMESTAMP) ts,
        CAST("Deviation" AS INTEGER) dev FROM read_csv('{tmp}', all_varchar=true, header=true))
        TO '{pq}' (FORMAT parquet)""")
    tmp.unlink()
    print("converted", m)
con.execute(f"CREATE VIEW rec AS SELECT * FROM read_parquet([{','.join(repr(str(pq_dir / f'{m}.parquet')) for m in months)}])")

# ---------------------------------------------------------------- GTFS versions and the version used for each day
vers = []
for d in sorted((RAW / "gtfs_hist").glob("mdb-*")):
    m_ = re.match(r"mdb-(\d{4}-\d\d-\d\d)-(\d{4}-\d\d-\d\d)", d.name)
    if m_ and (d / "trips.txt").exists():
        vers.append((d.name, m_.group(1), m_.group(2), d))
con.execute("CREATE TABLE st (v VARCHAR, trip_id VARCHAR, stop_id VARCHAR, seq INTEGER, dep_s INTEGER)")
con.execute("CREATE TABLE trips (v VARCHAR, trip_id VARCHAR, route VARCHAR, service_id VARCHAR, block_id VARCHAR)")
con.execute("CREATE TABLE active (v VARCHAR, d DATE, service_id VARCHAR, weekday_pattern BOOLEAN)")
for name, s, e, d in vers:
    con.execute(f"""INSERT INTO st SELECT '{name}', trip_id, stop_id, CAST(stop_sequence AS INTEGER),
        CAST(split_part(departure_time,':',1) AS INTEGER)*3600 + CAST(split_part(departure_time,':',2) AS INTEGER)*60
        + CAST(split_part(departure_time,':',3) AS INTEGER)
        FROM read_csv('{d}/stop_times.txt', all_varchar=true)""")
    con.execute(f"""INSERT INTO trips SELECT '{name}', t.trip_id, r.route_short_name, t.service_id, t.block_id
        FROM read_csv('{d}/trips.txt', all_varchar=true) t JOIN read_csv('{d}/routes.txt', all_varchar=true) r USING (route_id)""")
    cd = f"read_csv('{d}/calendar_dates.txt', all_varchar=true)" if (d / "calendar_dates.txt").exists() else \
        "(SELECT NULL::VARCHAR service_id, NULL::VARCHAR date, NULL::VARCHAR exception_type WHERE false)"
    con.execute(f"""INSERT INTO active
        WITH cal AS (SELECT * FROM read_csv('{d}/calendar.txt', all_varchar=true)),
        days AS (SELECT CAST(x AS DATE) d FROM range(DATE '{s}', DATE '{e}' + INTERVAL 1 DAY, INTERVAL 1 DAY) t(x)),
        base AS (SELECT days.d, cal.service_id FROM days, cal
            WHERE days.d BETWEEN strptime(cal.start_date,'%Y%m%d') AND strptime(cal.end_date,'%Y%m%d')
              AND CASE dayofweek(days.d) WHEN 0 THEN cal.sunday WHEN 1 THEN cal.monday WHEN 2 THEN cal.tuesday
                  WHEN 3 THEN cal.wednesday WHEN 4 THEN cal.thursday WHEN 5 THEN cal.friday ELSE cal.saturday END = '1'),
        ex AS (SELECT CAST(strptime(date,'%Y%m%d') AS DATE) d, service_id, exception_type FROM {cd}),
        act AS (SELECT d, service_id FROM base WHERE NOT EXISTS
                  (SELECT 1 FROM ex WHERE ex.d=base.d AND ex.service_id=base.service_id AND exception_type='2')
                UNION SELECT d, service_id FROM ex WHERE exception_type='1')
        SELECT '{name}', act.d, act.service_id,
               (cal.monday='1' AND cal.friday='1' AND cal.saturday='0' AND cal.sunday='0')
        FROM act JOIN cal USING (service_id)""")
vt = pd.DataFrame([(n, s, e) for n, s, e, _ in vers], columns=["v", "s", "e"])
# Day -> version: among versions covering the day, the latest start (most recent publication), then the shortest.
days = pd.date_range("2025-06-29", "2026-12-12").strftime("%Y-%m-%d")
pick = []
for day in days:
    c = vt[(vt.s <= day) & (vt.e >= day)].sort_values(["s", "e"], ascending=[False, True])
    if len(c):
        pick.append((day, c.v.iloc[0]))
con.register("ver_pick", pd.DataFrame(pick, columns=["d", "v"]))
con.execute("CREATE TABLE ver_for AS SELECT CAST(d AS DATE) d, v FROM ver_pick")
# Weekday service days: the chosen version runs a Mon-Fri-pattern service that day.
con.execute("""CREATE TABLE wdays AS SELECT DISTINCT a.d, a.v FROM active a JOIN ver_for f ON f.d=a.d AND f.v=a.v
               WHERE a.weekday_pattern""")
con.execute("""CREATE TABLE tmeta AS SELECT v, trip_id, min(dep_s) first_s, count(*) n_stops FROM st GROUP BY v, trip_id""")

section("GTFS versions used")
print(q("SELECT v, min(d) first_day, max(d) last_day, count(*) n_days FROM ver_for GROUP BY v ORDER BY first_day").to_string(index=False))

# ---------------------------------------------------------------- join (all months)
con.execute("""
CREATE TABLE cand AS
SELECT row_id, stop_id, route, dev, CAST(ts AS DATE) sd, hour(ts)*3600+minute(ts)*60+second(ts) s
FROM rec WHERE day_type='Weekday'
UNION ALL
SELECT row_id, stop_id, route, dev, CAST(ts AS DATE)-1, hour(ts)*3600+minute(ts)*60+second(ts)+86400
FROM rec WHERE day_type='Weekday' AND hour(ts) < 6
""")
con.execute("""
CREATE TABLE m AS
SELECT c.row_id, c.sd, c.dev, c.route, st.trip_id, st.seq, t.block_id, w.v
FROM cand c JOIN wdays w ON w.d=c.sd
JOIN st ON st.v=w.v AND st.stop_id=c.stop_id AND st.dep_s=c.s
JOIN trips t ON t.v=w.v AND t.trip_id=st.trip_id AND t.route=c.route
JOIN active a ON a.v=w.v AND a.d=c.sd AND a.service_id=t.service_id AND a.weekday_pattern
""")
con.execute("CREATE TABLE k AS SELECT row_id, count(*) k FROM m GROUP BY row_id")

section("G3 join rate by month (gate: every month with GTFS >= 95%; weekday records on weekday service days)")
g3 = q(f"""
WITH wk AS (SELECT r.row_id, strftime(CAST(r.ts AS DATE), '%Y-%m') mon, CAST(r.ts AS DATE) d FROM rec r
            WHERE r.day_type='Weekday' AND CAST(r.ts AS DATE) IN (SELECT d FROM wdays)),
     early AS (SELECT DISTINCT m.row_id FROM m JOIN tmeta tm ON tm.v=m.v AND tm.trip_id=m.trip_id WHERE tm.first_s < {EVE})
SELECT mon, count(*) n, avg((k.k IS NOT NULL)::INT) matched, avg((k.k=1)::INT) once, avg((k.k>1)::INT) ambiguous,
       count(DISTINCT d) n_days
FROM wk LEFT JOIN k USING (row_id) GROUP BY mon ORDER BY mon""")
print(g3.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
avail = q("""SELECT count(*) FILTER (WHERE v IS NOT NULL) have, count(*) n FROM
             (SELECT x::DATE d FROM range(DATE '2025-07-01', DATE '2026-11-24', INTERVAL 1 DAY) t(x)
              WHERE dayofweek(x) BETWEEN 1 AND 5) days LEFT JOIN ver_for USING (d)""").iloc[0]
print(f"Mon-Fri days 2025-07-01..2026-11-23 with a GTFS version: {avail.have} of {avail.n}")
res["G3"] = {"by_month": g3.to_dict("records"), "days_with_gtfs": int(avail.have), "days": int(avail.n),
             "pass": bool(g3.matched.min() >= 0.95 and avail.have / avail.n >= 0.90)}
um = q("""SELECT strftime(CAST(r.ts AS DATE), '%Y-%m') mon, r.route, count(*) n FROM rec r
          WHERE r.day_type='Weekday' AND CAST(r.ts AS DATE) IN (SELECT d FROM wdays) AND r.row_id NOT IN (SELECT row_id FROM k)
          GROUP BY ALL ORDER BY n DESC LIMIT 10""")
print("largest unmatched (month, route):", [tuple(x) for x in um.itertuples(index=False)])

# ---------------------------------------------------------------- window B observations (trips before 18:00)
con.execute(f"""
CREATE TABLE obs AS
SELECT m.sd, m.v, m.trip_id, m.route, m.seq, m.block_id, arg_min(m.dev, m.row_id) dev
FROM m JOIN k USING (row_id) JOIN tmeta tm ON tm.v=m.v AND tm.trip_id=m.trip_id
WHERE k.k=1 AND tm.first_s < {EVE} AND m.sd BETWEEN DATE '{WIN_B[0]}' AND DATE '{WIN_B[1]}'
GROUP BY ALL
""")
con.execute(f"""
CREATE TABLE tcov AS
SELECT w.d sd, t.trip_id, t.route, tm.first_s, (o.trip_id IS NOT NULL) present
FROM wdays w JOIN trips t ON t.v=w.v
JOIN active a ON a.v=w.v AND a.d=w.d AND a.service_id=t.service_id AND a.weekday_pattern
JOIN tmeta tm ON tm.v=w.v AND tm.trip_id=t.trip_id
LEFT JOIN (SELECT DISTINCT sd, trip_id FROM obs) o ON o.sd=w.d AND o.trip_id=t.trip_id
WHERE w.d BETWEEN DATE '{WIN_B[0]}' AND DATE '{WIN_B[1]}' AND tm.first_s < {EVE}
""")
wx = pd.read_csv(OUT / "weather_days.csv", dtype={"date": str})
bad_days = set(wx[wx.bad.astype(str) == "True"].date)
rd = q("SELECT route, CAST(sd AS VARCHAR) sd, avg(present::INT) cv, count(*) n FROM tcov GROUP BY route, sd")
rd["bad"] = rd.sd.isin(bad_days)
nb, ng = rd[rd.bad].sd.nunique(), rd[~rd.bad].sd.nunique()


def wdiff(df: pd.DataFrame) -> float:
    """Trip-weighted mean over routes of (bad-day coverage - other-day coverage), routes present in both groups."""
    g = df.groupby(["route", "bad"]).apply(lambda x: pd.Series({"cv": np.average(x.cv, weights=x.n), "n": x.n.sum()}),
                                           include_groups=False).unstack("bad")
    g = g.dropna()
    return float(np.average(g[("cv", True)] - g[("cv", False)], weights=g[("n", True)] + g[("n", False)]))


section(f"G2a coverage on bad-weather days, window B, trips before 18:00 (gate: |diff| < 5 pp and 95% CI within +-10 pp)")
d0 = wdiff(rd)
rng = np.random.default_rng(7)
bd, gd = sorted(rd[rd.bad].sd.unique()), sorted(rd[~rd.bad].sd.unique())
by_day = {d: x for d, x in rd.groupby("sd")}
boots = []
for _ in range(1000):
    pickd = list(rng.choice(bd, len(bd))) + list(rng.choice(gd, len(gd)))
    boots.append(wdiff(pd.concat([by_day[d].assign(sd=f"{d}#{i}") for i, d in enumerate(pickd)])))
lo, hi = np.percentile(boots, [2.5, 97.5])
print(f"bad-weather weekdays {nb}, other weekdays {ng}; coverage difference (bad - other) {d0*100:+.1f} pp, "
      f"95% CI {lo*100:+.1f} .. {hi*100:+.1f} pp (bootstrap over days, stratified)")
dc = q("SELECT CAST(sd AS VARCHAR) sd, avg(present::INT) cv FROM tcov GROUP BY sd ORDER BY sd")
dc["bad"] = dc.sd.isin(bad_days)
print("daily coverage: bad days " + " ".join(f"{r.sd[5:]}:{r.cv:.0%}" for r in dc[dc.bad].itertuples())
      + f" | other days median {dc[~dc.bad].cv.median():.0%} (P10 {dc[~dc.bad].cv.quantile(.1):.0%}, P90 {dc[~dc.bad].cv.quantile(.9):.0%})")
res["G2a"] = {"bad_days": nb, "other_days": ng, "diff_pp": d0 * 100, "ci_pp": [lo * 100, hi * 100],
              "pass": bool(abs(d0) < 0.05 and lo > -0.10 and hi < 0.10)}

# ---------------------------------------------------------------- I2 weather difference
section(f"I2 weather difference in deviation, window B, trips before 18:00 (event: late > {LATE_S}s)")
dv = q("SELECT CAST(sd AS VARCHAR) sd, dev FROM obs")
dv["bad"] = dv.sd.isin(bad_days)
rows = []
for flag, name in ((True, "bad-weather"), (False, "other")):
    x = dv[dv.bad == flag].dev
    rows.append((name, len(x), x.median(), -x.quantile(0.10), (x < -LATE_S).mean()))
    print(f"  {name:12s} obs {len(x):>10,}  median dev {x.median():+.0f}s  P90 lateness {-x.quantile(0.10):.0f}s  late>{LATE_S}s {(x < -LATE_S).mean():.1%}")
res["I2_weather"] = [dict(zip(["group", "n", "median_dev", "p90_lateness", "late_rate"], r)) for r in rows]
# by cause, for the record
for k in ("snow", "cold", "freezing_rain"):
    ds = set(wx[wx[k].astype(str) == "True"].date)
    x = dv[dv.sd.isin(ds)].dev
    if len(x):
        print(f"    {k:14s} days {len(ds & set(dv.sd)):>2}  late>{LATE_S}s {(x < -LATE_S).mean():.1%}  P90 lateness {-x.quantile(0.10):.0f}s")

# ---------------------------------------------------------------- I2 baseline Brier and decomposition
section(f"I2 baseline Brier: frequency by route x stop x time band, fit {TRAIN[0]}..{TRAIN[1]}, score {TEST[0]}..{TEST[1]}")
con.execute("""CREATE TABLE ob2 AS SELECT o.*, o.dev < -300 y, CASE WHEN tm.first_s < 6*3600 THEN 0 WHEN tm.first_s < 9*3600 THEN 1
               WHEN tm.first_s < 15*3600 THEN 2 ELSE 3 END band, st.stop_id
               FROM obs o JOIN tmeta tm ON tm.v=o.v AND tm.trip_id=o.trip_id
               JOIN st ON st.v=o.v AND st.trip_id=o.trip_id AND st.seq=o.seq""")
sc = q(f"""
WITH tr AS (SELECT * FROM ob2 WHERE sd BETWEEN DATE '{TRAIN[0]}' AND DATE '{TRAIN[1]}'),
     te AS (SELECT * FROM ob2 WHERE sd BETWEEN DATE '{TEST[0]}' AND DATE '{TEST[1]}'),
     c3 AS (SELECT route, stop_id, band, avg(y::INT) f, count(*) n FROM tr GROUP BY ALL),
     c1 AS (SELECT route, avg(y::INT) f FROM tr GROUP BY ALL),
     c0 AS (SELECT avg(y::INT) f FROM tr)
SELECT te.y::INT y, coalesce(CASE WHEN c3.n >= 10 THEN c3.f END, c1.f, (SELECT f FROM c0)) f,
       (c3.n >= 10) cell_used
FROM te LEFT JOIN c3 USING (route, stop_id, band) LEFT JOIN c1 USING (route)""")
y, f = sc.y.values.astype(float), sc.f.values.astype(float)
brier = float(np.mean((f - y) ** 2))
ob = y.mean()
bins = np.round(f, 2)
g = pd.DataFrame({"b": bins, "f": f, "y": y}).groupby("b").agg(n=("y", "size"), fk=("f", "mean"), ok=("y", "mean"))
rel = float((g.n * (g.fk - g.ok) ** 2).sum() / len(y))
reso = float((g.n * (g.ok - ob) ** 2).sum() / len(y))
unc = float(ob * (1 - ob))
print(f"test obs {len(y):,} (cell estimate used for {sc.cell_used.fillna(False).mean():.1%}); base rate {ob:.2%}")
print(f"Brier {brier:.4f}   climatology Brier (=uncertainty) {unc:.4f}   skill vs climatology {1 - brier/unc:+.1%}")
print(f"decomposition (forecasts binned to 0.01): reliability {rel:.4f}  resolution {reso:.4f}  uncertainty {unc:.4f}"
      f"   (REL - RES + UNC = {rel - reso + unc:.4f})")
print(f"resolution / uncertainty = {reso/unc:.1%}")
res["I2_brier"] = {"n": len(y), "base_rate": ob, "brier": brier, "reliability": rel, "resolution": reso, "uncertainty": unc}

# ---------------------------------------------------------------- record-only additions (2026-11-25, after ADR 0005)
section("Added: winter check, do low-coverage route-days show a lower observed late rate? (same method as window A)")
rl = q(f"""
WITH c AS (SELECT route, sd, avg(present::INT) cv FROM tcov GROUP BY route, sd),
l AS (SELECT route, sd, avg((dev < -{LATE_S})::INT) late FROM obs GROUP BY route, sd)
SELECT c.route, CAST(c.sd AS VARCHAR) sd, c.cv, l.late FROM c JOIN l USING (route, sd)""")


def demean(df: pd.DataFrame, cols: list[str], by: list[str], iters: int = 50) -> pd.DataFrame:
    o = df[cols].copy()
    for _ in range(iters):
        for b in by:
            o -= o.groupby(df[b]).transform("mean")
    return o


def slope(df: pd.DataFrame, by: list[str]) -> float:
    r = demean(df, ["cv", "late"], by)
    return float((r.cv * r.late).sum() / (r.cv ** 2).sum())


rng2 = np.random.default_rng(1)
dlist = rl.sd.unique()
by_d = {d: x for d, x in rl.groupby("sd")}
res["added_cov_late"] = {}
for by, label in ((["route"], "within route"), (["route", "sd"], "within route and day")):
    b = slope(rl, by)
    bs = []
    for _ in range(300):
        pk = rng2.choice(dlist, len(dlist))
        bs.append(slope(pd.concat([by_d[d].assign(sd=f"{d}#{i}") for i, d in enumerate(pk)]), by))
    lo2, hi2 = np.percentile(bs, [2.5, 97.5])
    print(f"  {label:22s}: +10 pp coverage -> late rate {b*10:+.2f} pp  (95% CI {lo2*10:+.2f} .. {hi2*10:+.2f})")
    res["added_cov_late"][label] = {"per_10pp": b * 10, "ci": [lo2 * 10, hi2 * 10]}
print(f"  route-days {len(rl):,}; within-route SD of coverage {demean(rl, ['cv'], ['route']).cv.std():.3f}")

section("Added: winter variance decomposition (trip-day late share, Henderson I, same method as window A)")
z = q(f"SELECT trip_id, CAST(sd AS VARCHAR) sd, avg((dev < -{LATE_S})::INT) z FROM obs GROUP BY trip_id, sd")
N = len(z)
Tt = z.groupby("trip_id").z.agg(["sum", "count"])
Td = z.groupby("sd").z.agg(["sum", "count"])
R, D = len(Tt), len(Td)
sA, sB, s0 = (Tt["sum"] ** 2 / Tt["count"]).sum(), (Td["sum"] ** 2 / Td["count"]).sum(), (z.z ** 2).sum()
cf = z.z.sum() ** 2 / N
kt, kd = (Tt["count"] ** 2).sum() / N, (Td["count"] ** 2).sum() / N
A = np.array([[N - kt, R - kd, R - 1], [D - kt, N - kd, D - 1], [N - kt, N - kd, N - 1]], dtype=float)
vt_, vd_, ve_ = np.linalg.solve(A, np.array([sA - cf, sB - cf, s0 - cf]))
tv = vt_ + vd_ + ve_
print(f"  {N:,} trip-days, {R:,} trips, {D} days; share: trip {vt_/tv:.1%}  day {vd_/tv:.1%}  trip-x-day {ve_/tv:.1%}")
print(f"  SD(trip) {np.sqrt(max(vt_,0)):.3f}  SD(day) {np.sqrt(max(vd_,0)):.3f}  SD(trip x day) {np.sqrt(max(ve_,0)):.3f}")
res["added_decomp"] = {"trip_days": N, "trips": R, "days": D, "var_trip": vt_, "var_day": vd_, "var_trip_x_day": ve_}

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "window_b.json").write_text(json.dumps(res, indent=1, default=float))
