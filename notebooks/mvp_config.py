"""Settings for the MVP data preparation (route 91 toward St. Norbert).

Every number that a reader may want to question lives here, with the reason next to it.
The notebook and mvp_prep.py import from this file; nothing else hard-codes these values.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parents[1]          # repository root (this file sits in notebooks/)
DATA_DIR = ROOT / "data" / "mvp"

DATA_PATH = DATA_DIR / "route91_st_norbert.csv"     # main table, probe/export_mvp_slice.py
WEATHER_PATH = DATA_DIR / "weather_daily.csv"       # probe/export_mvp_extras.py
CALENDAR_PATH = DATA_DIR / "calendar_daily.csv"     # probe/export_mvp_extras.py
RIDERSHIP_PATH = DATA_DIR / "stop_ridership.csv"    # probe/export_mvp_extras.py
PREPARED_PATH = DATA_DIR / "route91_st_norbert_prepared.parquet"   # output of the notebook

# ---------------------------------------------------------------- targets (BO-1, BO-2)
# deviation = scheduled - actual, in seconds: negative = late, positive = early.
LATE_S = 300        # a: late by more than 5 minutes  -> late_5min  = deviation < -300
EARLY_S = 60        # b: early by more than 60 s      -> early_60s = deviation > 60

# ---------------------------------------------------------------- cleaning
MAX_ABS_DEV_S = 3600    # |deviation| above one hour is a recording error, not service

# ---------------------------------------------------------------- period
FIRST_DATE = "2025-07-01"   # side tables start here
LAST_DATE = "2026-11-23"    # last day of the recent table at export time
# No source covers these weekdays: they fall between the archive (to 2026-09-30)
# and the recent table (from 2026-10-10).
SOURCE_GAP = ("2026-10-01", "2026-10-09")

# ---------------------------------------------------------------- time split
# PROVISIONAL. The modelling notebook fixes the rolling time split (test design) before any
# model is trained. Here it is only used to fit the standardization on training rows, so that
# no statistic of later rows leaks into the scaled features.
TRAIN_END = "2026-06-30"

# ---------------------------------------------------------------- history (lag) features
# Rates over the last N *observed* service days of the same (stop, scheduled time of day),
# always ending on the day before the prediction day.
LAG_WINDOWS = (5, 20)                 # about one week and about one month of service days
LAG_MIN_OBS = {5: 3, 20: 5}           # fewer prior observations than this -> NaN (too little history)

# ---------------------------------------------------------------- ridership
# ASSUMPTION: the portal does not publish the boundaries of its time periods.
# [start hour, end hour) on the scheduled departure time. Fixed before looking at model results.
TIME_PERIODS = [(0, 9, "Morning"), (9, 15, "Mid-Day"), (15, 18, "PM Peak"), (18, 24, "Evening")]

# ---------------------------------------------------------------- weather
# Same-day observed weather is not known the day before (ADR 0003): features use day d - 1.
WEATHER_LAG_DAYS = 1
# Open-Meteo weather_text grouped into four classes for one-hot encoding.
WEATHER_GROUPS = {
    "clear": ["clear", "mainly clear", "partly cloudy"],
    "overcast": ["overcast"],
    "rain": ["light drizzle", "drizzle", "dense drizzle", "light rain", "rain", "heavy rain"],
    "snow": ["light snow", "snow", "heavy snow"],
}
