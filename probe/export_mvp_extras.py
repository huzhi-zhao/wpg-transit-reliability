# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""Small side tables that can be joined to the MVP slice (data/mvp/route91_st_norbert.csv).

  data/mvp/weather_daily.csv   one row per date: Open-Meteo archive daily weather near route 91
                               (temperature, precipitation, rain, snowfall, wind, WMO weather code
                               and its text label)
  data/mvp/calendar_daily.csv  one row per date: statutory holiday, day before / after a holiday,
                               City of Winnipeg snow parking bans in force (portal mfzv-893p)
  data/mvp/stop_ridership.csv  route 91 weekday average boardings / alightings per stop, time period
                               and schedule period (portal bv6q-du26)

Weather is observed, not forecast: using same-day weather as a feature is not "known the day
before" (ADR 0003). Use the previous day's values, or treat same-day values as an upper bound.

Run   : uv run probe/export_mvp_extras.py
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/mvp"
FIRST, LAST = dt.date(2025, 7, 1), dt.date(2026, 11, 23)
LAT, LON = 49.78, -97.155  # middle of route 91 St. Norbert stops
PORTAL = "https://data.winnipeg.ca/resource"
STOPS = ["60016", "60017", "60019", "60020", "60021", "60022", "60026", "60028",
         "60033", "60058", "60061", "60064", "60089", "60746", "60782", "60805"]
HOLIDAYS = {  # same list as probe/weather_days.py: Manitoba statutory holidays, Sunday service
    "2025-07-01", "2025-08-04", "2025-09-01", "2025-09-30", "2025-10-13", "2025-11-11", "2025-12-25",
    "2025-12-26", "2026-01-01", "2026-02-16", "2026-04-03", "2026-05-18", "2026-07-01", "2026-08-03",
    "2026-09-07", "2026-09-30", "2026-10-12", "2026-11-11",
}
WMO = {  # WMO weather interpretation codes used by Open-Meteo
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 56: "light freezing drizzle",
    57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "light freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "rain showers", 82: "violent rain showers", 85: "light snow showers",
    86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def write(path: pathlib.Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{path.relative_to(ROOT)}: {len(rows)} rows")


def weather() -> None:
    daily = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "rain_sum",
             "snowfall_sum", "wind_speed_10m_max", "weather_code"]
    r = requests.get("https://archive-api.open-meteo.com/v1/archive", timeout=60, params={
        "latitude": LAT, "longitude": LON, "start_date": FIRST.isoformat(), "end_date": LAST.isoformat(),
        "daily": ",".join(daily), "timezone": "America/Winnipeg"})
    r.raise_for_status()
    d = r.json()["daily"]
    rows = []
    for i, day in enumerate(d["time"]):
        row = {"date": day} | {k: d[k][i] for k in daily}
        row["weather_text"] = WMO.get(d["weather_code"][i], "unknown")
        rows.append(row)
    write(OUT / "weather_daily.csv", rows)


def calendar() -> None:
    bans = requests.get(f"{PORTAL}/mfzv-893p.json", timeout=60, params={
        "$where": f"ban_end >= '{FIRST}' AND ban_start <= '{LAST}T23:59:59'", "$limit": 1000}).json()
    rows, day = [], FIRST
    while day <= LAST:
        iso = day.isoformat()
        prev, nxt = (day - dt.timedelta(days=1)).isoformat(), (day + dt.timedelta(days=1)).isoformat()
        start, end = f"{iso}T00:00:00", f"{iso}T23:59:59"
        active = [b["description"] for b in bans if b["ban_start"] <= end and b["ban_end"] >= start]
        rows.append({
            "date": iso,
            "is_holiday": iso in HOLIDAYS,
            "day_before_holiday": nxt in HOLIDAYS,
            "day_after_holiday": prev in HOLIDAYS,
            "snow_route_ban": any("SNOW ROUTE" in a for a in active),
            "residential_ban": any("RESIDENTIAL" in a for a in active),
        })
        day += dt.timedelta(days=1)
    write(OUT / "calendar_daily.csv", rows)


def ridership() -> None:
    stops = ",".join(STOPS)
    data = requests.get(f"{PORTAL}/bv6q-du26.json", timeout=60, params={
        "$where": f"route_number = '91' AND day_type = 'Weekday' "
                  f"AND schedule_period_start_date >= '2025-06-29' AND stop_number in({stops})",
        "$limit": 50000}).json()
    rows = [{
        "schedule_period_name": r["schedule_period_name"],
        "period_start": r["schedule_period_start_date"][:10],
        "period_end": r["schedule_period_end_date"][:10],
        "stop_number": r["stop_number"],
        "time_period": r["time_period"],
        "average_boardings": r["average_boardings"],
        "average_alightings": r["average_alightings"],
    } for r in data]
    rows.sort(key=lambda r: (r["period_start"], r["stop_number"], r["time_period"]))
    write(OUT / "stop_ridership.csv", rows)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    weather()
    calendar()
    ridership()
