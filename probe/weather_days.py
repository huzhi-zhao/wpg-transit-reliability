# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""P0 G4: count bad-weather weekdays, using the definition registered in
docs/dev/design/20261124-feasibility-probe.md §2.3.

  snow day          Open-Meteo archive snowfall_sum >= 5 cm (downtown 49.895, -97.138)
  extreme-cold day  ECCC WINNIPEG INTL A (5023227) daily minimum <= -30 °C
                    (hourly minimum when the daily value is missing)
  freezing-rain day an hourly weather description at 5023227 contains "Freezing Rain"
                    ("Freezing Drizzle" and "Freezing Fog" are counted separately, for reference only)

Weekdays are Mon-Fri minus Manitoba statutory holidays (list below; Winnipeg Transit runs
Sunday service on these). Window: 2025-07-01 .. 2026-11-23, minus 2026-10-01 .. 2026-10-09,
which neither on-time table covers.

Run   : uv run probe/weather_days.py
Output: printed report + data/out/weather_days.csv (one row per weekday with the three flags)
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIRST, LAST = dt.date(2025, 7, 1), dt.date(2026, 11, 23)
GAP = (dt.date(2026, 10, 1), dt.date(2026, 10, 9))
SNOW_CM, COLD_C = 5.0, -30.0
HOLIDAYS = {  # Manitoba statutory holidays and Winnipeg Transit Sunday-service days in the window
    "2025-07-01", "2025-08-04", "2025-09-01", "2025-09-30", "2025-10-13", "2025-11-11", "2025-12-25",
    "2025-12-26", "2026-01-01", "2026-02-16", "2026-04-03", "2026-05-18", "2026-07-01", "2026-08-03",
    "2026-09-07", "2026-09-30", "2026-10-12", "2026-11-11",
}
ECCC = "https://api.weather.gc.ca/collections/{c}/items"


def eccc(collection: str, station: str) -> list[dict]:
    rows, offset = [], 0
    while True:
        r = requests.get(ECCC.format(c=collection), timeout=120, params={
            "f": "json", "CLIMATE_IDENTIFIER": station, "limit": 10000, "offset": offset,
            "datetime": f"{FIRST}T00:00:00Z/{LAST + dt.timedelta(days=1)}T12:00:00Z"})
        r.raise_for_status()
        feats = r.json()["features"]
        rows += [f["properties"] for f in feats]
        if len(feats) < 10000:
            return rows
        offset += 10000


om = requests.get("https://archive-api.open-meteo.com/v1/archive", timeout=120, params={
    "latitude": 49.895, "longitude": -97.138, "start_date": str(FIRST), "end_date": str(LAST),
    "daily": "snowfall_sum", "timezone": "America/Winnipeg"}).json()["daily"]
snow = dict(zip(om["time"], om["snowfall_sum"]))

daily_min = {p["LOCAL_DATE"][:10]: p["MIN_TEMPERATURE"] for p in eccc("climate-daily", "5023227")}
hourly = eccc("climate-hourly", "5023227")
h_min: dict[str, float] = {}
frz: dict[str, bool] = {}
fdz: dict[str, bool] = {}
ffg: dict[str, bool] = {}
desc_missing = 0
for p in hourly:
    d = p["LOCAL_DATE"][:10]
    if p["TEMP"] is not None:
        h_min[d] = min(h_min.get(d, 99.0), p["TEMP"])
    desc = p.get("WEATHER_ENG_DESC") or ""
    if desc in ("", "NA"):
        desc_missing += 1
    frz[d] = frz.get(d, False) or ("Freezing Rain" in desc)
    fdz[d] = fdz.get(d, False) or ("Freezing Drizzle" in desc)
    ffg[d] = ffg.get(d, False) or ("Freezing Fog" in desc)

rows = []
d = FIRST
while d <= LAST:
    s = str(d)
    if d.weekday() < 5 and s not in HOLIDAYS and not (GAP[0] <= d <= GAP[1]):
        tmin = daily_min.get(s)
        tmin = tmin if tmin is not None else h_min.get(s)
        rows.append({"date": s, "snowfall_cm": snow.get(s), "tmin_c": tmin,
                     "snow": (snow.get(s) or 0) >= SNOW_CM,
                     "cold": tmin is not None and tmin <= COLD_C,
                     "freezing_rain": frz.get(s, False),
                     "ref_freezing_drizzle": fdz.get(s, False), "ref_freezing_fog": ffg.get(s, False)})
    d += dt.timedelta(days=1)
for r in rows:
    r["bad"] = r["snow"] or r["cold"] or r["freezing_rain"]

out = ROOT / "data/out"
out.mkdir(parents=True, exist_ok=True)
with open(out / "weather_days.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

n = lambda k, rs=rows: sum(r[k] for r in rs)  # noqa: E731
print(f"weekdays in window: {len(rows)}  (hourly rows {len(hourly):,}, without weather description {desc_missing:,})")
print(f"missing inputs: snowfall {sum(r['snowfall_cm'] is None for r in rows)}, tmin {sum(r['tmin_c'] is None for r in rows)}")
print(f"bad-weather weekdays: {n('bad')}   snow {n('snow')}  cold {n('cold')}  freezing rain {n('freezing_rain')}")
for label, lo, hi in (("window B 2025-12..2026-03", "2025-12-01", "2026-03-31"), ("window A 2026-10-10..11-23", "2026-10-10", "2026-11-23")):
    sub = [r for r in rows if lo <= r["date"] <= hi]
    print(f"  {label}: {n('bad', sub)} of {len(sub)} weekdays  (snow {n('snow', sub)}, cold {n('cold', sub)}, freezing rain {n('freezing_rain', sub)})")
print(f"reference only (not in the definition): weekdays with freezing drizzle {n('ref_freezing_drizzle')}, freezing fog {n('ref_freezing_fog')}; "
      "weather descriptions are mostly every 3 hours, so short events can be missed")
print("bad days:", " ".join(r["date"] + ("S" if r["snow"] else "") + ("C" if r["cold"] else "") + ("F" if r["freezing_rain"] else "") for r in rows if r["bad"]))
