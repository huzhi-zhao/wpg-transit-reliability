# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""P0 G3: list historical Winnipeg Transit GTFS versions and download the ones covering a date range.

Sources: Mobility Database (feed mdb-717) and Transitland (feed f-cbfg-winnipegtransit).
Credentials come from .env (see .env.example) and are sent only in request headers/bodies.

Run   : uv run probe/gtfs_history.py                     # list versions from both sources
        uv run probe/gtfs_history.py --download 2025-07-01 2026-11-23
Output: data/raw/gtfs_hist/<source>-<service start>-<service end>/ (unzipped), plus versions.tsv
"""

from __future__ import annotations

import datetime as dt
import io
from zoneinfo import ZoneInfo
import pathlib
import sys
import zipfile

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/raw/gtfs_hist"
MDB = "https://api.mobilitydatabase.org/v1"
TL = "https://transit.land/api/v2/rest"


def env() -> dict[str, str]:
    vals = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip("'\"")
    return vals


def mdb_versions(refresh: str) -> tuple[list[dict], dict]:
    r = requests.post(f"{MDB}/tokens", json={"refresh_token": refresh}, timeout=60)
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    out, offset = [], 0
    while True:
        r = requests.get(f"{MDB}/gtfs_feeds/mdb-717/datasets", headers=h, timeout=60,
                         params={"limit": 100, "offset": offset})
        r.raise_for_status()
        page = r.json()
        out += [{"source": "mdb", "id": d["id"], "fetched": (d.get("downloaded_at") or "")[:10],
                 "start": d.get("service_date_range_start") or "", "end": d.get("service_date_range_end") or "",
                 "sha1": d.get("hash") or "", "url": d.get("hosted_url") or ""} for d in page]
        if len(page) < 100:
            return out, h
        offset += 100


def tl_versions(key: str) -> list[dict]:
    h = {"apikey": key}
    out, after = [], None
    while True:
        params = {"limit": 100}
        if after:
            params["after"] = after
        r = requests.get(f"{TL}/feeds/f-cbfg-winnipegtransit/feed_versions", headers=h, params=params, timeout=60)
        r.raise_for_status()
        j = r.json()
        for v in j.get("feed_versions", []):
            out.append({"source": "tl", "id": v["sha1"], "fetched": (v.get("fetched_at") or "")[:10],
                        "start": v.get("earliest_calendar_date") or "", "end": v.get("latest_calendar_date") or "",
                        "sha1": v["sha1"], "url": f"{TL}/feed_versions/{v['sha1']}/download"})
        after = (j.get("meta") or {}).get("after")
        if not after or not j.get("feed_versions"):
            return out


def norm(d: str) -> str:
    """Local service date. Transitland gives local dates; Mobility Database gives UTC timestamps."""
    if "T" in d:
        t = dt.datetime.fromisoformat(d.replace("Z", "+00:00"))
        return t.astimezone(ZoneInfo("America/Winnipeg")).date().isoformat()
    d = d.replace("-", "")[:8]
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d


def main() -> None:
    e = env()
    rows, mdb_h = [], {}
    if e.get("MOBILITY_DB_REFRESH_TOKEN"):
        try:
            m, mdb_h = mdb_versions(e["MOBILITY_DB_REFRESH_TOKEN"])
            rows += m
        except requests.HTTPError as ex:
            print("Mobility Database:", ex.response.status_code, ex.response.text[:200])
    if e.get("TRANSITLAND_API_KEY"):
        try:
            rows += tl_versions(e["TRANSITLAND_API_KEY"])
        except requests.HTTPError as ex:
            print("Transitland:", ex.response.status_code, ex.response.text[:200])
    for r in rows:
        r["start"], r["end"] = norm(r["start"]), norm(r["end"])
    rows.sort(key=lambda r: (r["start"], r["source"]))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "versions.tsv", "w") as f:
        f.write("source\tfetched\tstart\tend\tsha1\tid\n")
        for r in rows:
            f.write(f"{r['source']}\t{r['fetched']}\t{r['start']}\t{r['end']}\t{r['sha1']}\t{r['id']}\n")
    seen = {}
    for r in rows:  # one line per distinct service period
        seen.setdefault((r["start"], r["end"]), set()).add(r["source"])
    print(f"{len(rows)} versions; distinct service periods:")
    for (s, t), src in sorted(seen.items()):
        if s >= "2024-06":
            print(f"  {s} .. {t}   {','.join(sorted(src))}")

    if len(sys.argv) == 4 and sys.argv[1] == "--download":
        lo, hi = sys.argv[2], sys.argv[3]
        picked = {}
        # Mobility Database versions overlapping [lo, hi], one per service period (latest fetch).
        # Its files are publicly hosted; Transitland's free plan lists versions but refuses downloads (401).
        for r in sorted((r for r in rows if r["source"] == "mdb"), key=lambda r: r["fetched"]):
            if r["start"] and r["end"] >= lo and r["start"] <= hi:
                picked[(r["start"], r["end"])] = r
        for (s, t), r in sorted(picked.items()):
            d = OUT / f"{r['source']}-{s}-{t}"
            if (d / "trips.txt").exists():
                print("have", d.name)
                continue
            resp = requests.get(r["url"], timeout=300)
            resp.raise_for_status()
            zipfile.ZipFile(io.BytesIO(resp.content)).extractall(d)
            print("downloaded", d.name, f"{len(resp.content)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
