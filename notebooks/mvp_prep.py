"""Data preparation steps for the MVP (route 91 toward St. Norbert).

One function per step, in the order the notebook runs them. `prepare()` runs the whole chain and
returns the modelling table, so the modelling notebook can rebuild it without this notebook.

Every function returns a new DataFrame and leaves its input unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import mvp_config as cfg

UNIT = ["stop_number", "time_of_day"]   # one scheduled departure at one stop, repeated each weekday


# ================================================================ load
def load_all() -> dict[str, pd.DataFrame]:
    """Read the four MVP files with the types the later steps expect."""
    return {
        "main": pd.read_csv(cfg.DATA_PATH, dtype={"route_number": str, "stop_number": str}),
        "weather": pd.read_csv(cfg.WEATHER_PATH, parse_dates=["date"]),
        "calendar": pd.read_csv(cfg.CALENDAR_PATH, parse_dates=["date"]),
        "ridership": pd.read_csv(cfg.RIDERSHIP_PATH, dtype={"stop_number": str},
                                 parse_dates=["period_start", "period_end"]),
    }


# ================================================================ 3. pre-processing
def parse_times(df: pd.DataFrame) -> pd.DataFrame:
    """Parse scheduled_time with a fixed format (a bad value raises) and add service_date."""
    out = df.copy()
    out["scheduled_time"] = pd.to_datetime(out["scheduled_time"], format="%Y-%m-%d %H:%M:%S")
    out["service_date"] = out["scheduled_time"].dt.normalize()
    return out


def drop_conflicting_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Drop every copy of a (stop, scheduled time) key that occurs more than once.

    In this slice all such copies disagree on deviation, so no copy can be preferred.
    """
    dup = df.duplicated(["stop_number", "scheduled_time"], keep=False)
    return df[~dup].reset_index(drop=True)


def drop_extreme_deviation(df: pd.DataFrame, limit: int = cfg.MAX_ABS_DEV_S) -> pd.DataFrame:
    return df[df["deviation"].abs() <= limit].reset_index(drop=True)


def real_weekdays(calendar: pd.DataFrame, start=None, end=None) -> pd.DatetimeIndex:
    """Monday to Friday and not a statutory holiday, within [start, end]."""
    cal = calendar
    if start is not None:
        cal = cal[cal["date"] >= pd.Timestamp(start)]
    if end is not None:
        cal = cal[cal["date"] <= pd.Timestamp(end)]
    keep = (cal["date"].dt.day_of_week < 5) & ~cal["is_holiday"]
    return pd.DatetimeIndex(cal.loc[keep, "date"]).sort_values()


def keep_real_weekdays(df: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """Keep rows whose service date is a real weekday (drops Weekday-labelled rows on weekends/holidays)."""
    return df[df["service_date"].isin(real_weekdays(calendar))].reset_index(drop=True)


def check_side_tables(weather, calendar, ridership, df) -> pd.DataFrame:
    """Assert that the side tables can be joined safely. Returns the schedule-period table."""
    full_range = pd.date_range(cfg.FIRST_DATE, cfg.LAST_DATE, freq="D")
    for name, t in [("weather", weather), ("calendar", calendar)]:
        assert t["date"].is_unique, f"{name}: duplicate dates"
        assert set(t["date"]) == set(full_range), f"{name}: missing or extra dates"
        assert t.notna().all().all(), f"{name}: empty cells"
    assert not ridership.duplicated(["schedule_period_name", "stop_number", "time_period"]).any()
    periods = (ridership.drop_duplicates("schedule_period_name")
               .sort_values("period_start")[["schedule_period_name", "period_start", "period_end"]]
               .reset_index(drop=True))
    gaps = (periods["period_start"].shift(-1) - periods["period_end"]).dt.days.dropna()
    assert (gaps == 1).all(), "schedule periods overlap or leave a gap"
    per = ridership.groupby("schedule_period_name").agg(stops=("stop_number", "nunique"),
                                                        time_periods=("time_period", "nunique"))
    assert (per["stops"] == 16).all() and (per["time_periods"] == 4).all()
    assert set(df["stop_number"]) <= set(ridership["stop_number"])
    return periods.merge(per, left_on="schedule_period_name", right_index=True)


# ================================================================ 4. transformation
def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    t = out["scheduled_time"]
    out["hour"] = t.dt.hour
    out["minute"] = t.dt.minute
    out["minute_of_day"] = t.dt.hour * 60 + t.dt.minute + t.dt.second / 60
    out["time_of_day"] = t.dt.strftime("%H:%M:%S")
    out["day_of_week"] = t.dt.day_of_week          # 0 = Monday
    out["month"] = t.dt.month
    return out


def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["late_5min"] = out["deviation"] < -cfg.LATE_S
    out["early_60s"] = out["deviation"] > cfg.EARLY_S
    return out


def add_stop_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse WKT 'POINT (lon lat)' and add stop_order (0 = northernmost).

    The data has no stop sequence; route 91 runs south toward St. Norbert, so latitude
    order approximates route order.
    """
    out = df.copy()
    xy = out["location"].str.extract(r"POINT \((?P<lon>\S+) (?P<lat>\S+)\)").astype(float)
    out["stop_lon"], out["stop_lat"] = xy["lon"], xy["lat"]
    lat = out.groupby("stop_number")["stop_lat"].first().sort_values(ascending=False)
    out["stop_order"] = out["stop_number"].map({s: i for i, s in enumerate(lat.index)})
    return out


def add_history_features(df: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """History features, using only service days before the row's own day.

    - hist_{late,early}_{N}d: rate over the last N *observed* days of the same (stop, time of day).
      Missing days are skipped, never imputed. Too few prior observations -> NaN.
    - hist_n_obs: number of prior observations of the unit (capped at the largest window).
    - route_prev_{late,early}: rate over all rows of the previous observed service day.
    - days_since_last_observed: real weekdays between this day and the previous observed day
      (1 = the day before had data; larger = the history is stale).
    """
    out = df.sort_values(UNIT + ["service_date"]).copy()
    g = out.groupby(UNIT, sort=False)
    for target, short in [("late_5min", "late"), ("early_60s", "early")]:
        prior = g[target].shift(1).astype(float)             # strictly before this day
        for n in cfg.LAG_WINDOWS:
            out[f"hist_{short}_{n}d"] = (prior.groupby([out[c] for c in UNIT], sort=False)
                                         .rolling(n, min_periods=cfg.LAG_MIN_OBS[n]).mean()
                                         .reset_index(level=[0, 1], drop=True))
    out["hist_n_obs"] = g.cumcount().clip(upper=max(cfg.LAG_WINDOWS))

    daily = out.groupby("service_date")[["late_5min", "early_60s"]].mean().sort_index()
    prev = daily.shift(1).rename(columns={"late_5min": "route_prev_late", "early_60s": "route_prev_early"})
    days = real_weekdays(calendar)
    pos = pd.Series(np.arange(len(days)), index=days)
    observed = daily.index
    gap = pd.Series(pos.loc[observed].values, index=observed).diff()
    prev["days_since_last_observed"] = gap
    out = out.merge(prev, left_on="service_date", right_index=True, how="left")
    return out.sort_values(["scheduled_time", "stop_number"]).reset_index(drop=True)


def weather_group(text: pd.Series) -> pd.Series:
    lookup = {label: group for group, labels in cfg.WEATHER_GROUPS.items() for label in labels}
    return text.map(lookup)


def join_weather(df: pd.DataFrame, weather: pd.DataFrame, lag_days: int = cfg.WEATHER_LAG_DAYS,
                 prefix: str = "wx_prev_") -> pd.DataFrame:
    """Join the weather of day d - lag_days to service date d (lag_days=0 only for an upper-bound run)."""
    w = weather.copy()
    w["group"] = weather_group(w["weather_text"])
    assert w["group"].notna().all(), "weather_text label without a group"
    onehot = pd.get_dummies(w["group"], prefix="is").astype(int)
    onehot = onehot.reindex(columns=[f"is_{g}" for g in cfg.WEATHER_GROUPS], fill_value=0)
    num = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "rain_sum",
           "snowfall_sum", "wind_speed_10m_max"]
    w = pd.concat([w[["date"] + num], onehot], axis=1)
    w["date"] = w["date"] + pd.Timedelta(days=lag_days)      # the weather of d-1 is used on day d
    w = w.rename(columns={c: prefix + c for c in w.columns if c != "date"})
    out = df.merge(w, left_on="service_date", right_on="date", how="left", validate="many_to_one")
    return out.drop(columns="date")


CALENDAR_FEATURES = ["day_before_holiday", "day_after_holiday", "snow_route_ban", "residential_ban"]


def join_calendar(df: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    c = calendar[["date"] + CALENDAR_FEATURES].copy()
    c[CALENDAR_FEATURES] = c[CALENDAR_FEATURES].astype(int)
    out = df.merge(c, left_on="service_date", right_on="date", how="left", validate="many_to_one")
    return out.drop(columns="date")


def time_period(hour: pd.Series) -> pd.Series:
    bins = [lo for lo, _, _ in cfg.TIME_PERIODS] + [cfg.TIME_PERIODS[-1][1]]
    labels = [name for _, _, name in cfg.TIME_PERIODS]
    return pd.cut(hour, bins=bins, labels=labels, right=False).astype(str)


def schedule_period(dates: pd.Series, ridership: pd.DataFrame) -> pd.Series:
    """Name of the schedule period that contains each date; NaN when no period covers it."""
    periods = ridership.drop_duplicates("schedule_period_name")[["schedule_period_name", "period_start", "period_end"]]
    out = pd.Series(np.nan, index=dates.index, dtype=object)
    for p in periods.itertuples():
        out[(dates >= p.period_start) & (dates <= p.period_end)] = p.schedule_period_name
    return out


RIDERSHIP_FEATURES = ["average_boardings", "average_alightings"]


def join_ridership(df: pd.DataFrame, ridership: pd.DataFrame) -> pd.DataFrame:
    """Join weekday average boardings / alightings on (schedule period, stop, time period).

    Dates after the last published period get NaN here; carry_forward_ridership() fills them.
    """
    out = df.copy()
    out["time_period"] = time_period(out["hour"])
    out["schedule_period_name"] = schedule_period(out["service_date"], ridership)
    r = ridership[["schedule_period_name", "stop_number", "time_period"] + RIDERSHIP_FEATURES]
    return out.merge(r, on=["schedule_period_name", "stop_number", "time_period"], how="left",
                     validate="many_to_one")


# ================================================================ 5. standardization
def numeric_features(df: pd.DataFrame) -> list[str]:
    """Continuous features that a linear model should see on a common scale (no 0/1 columns)."""
    base = ["minute_of_day", "stop_lat", "stop_lon", "stop_order", "hist_n_obs",
            "route_prev_late", "route_prev_early", "days_since_last_observed"] + RIDERSHIP_FEATURES
    hist = [c for c in df.columns if c.startswith("hist_") and c.endswith("d")]
    wx = [c for c in df.columns if c.startswith("wx_prev_") and not c.startswith("wx_prev_is_")]
    return [c for c in base + hist + wx if c in df.columns]


def fit_scaler(df: pd.DataFrame, columns: list[str], train_end: str = cfg.TRAIN_END) -> pd.DataFrame:
    """Mean and standard deviation of each column over training rows only (service_date <= train_end)."""
    train = df[df["service_date"] <= pd.Timestamp(train_end)]
    stats = pd.DataFrame({"mean": train[columns].mean(), "std": train[columns].std(ddof=0)})
    stats["std"] = stats["std"].replace(0, 1.0)       # a constant column stays 0 after scaling
    return stats


def apply_scaler(df: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col, row in stats.iterrows():
        out[f"z_{col}"] = (out[col] - row["mean"]) / row["std"]
    return out


# ================================================================ 6. completeness
def completeness_by_day(df: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """One row per real weekday from the first record to LAST_DATE: rows observed, in source gap, missing."""
    days = real_weekdays(calendar, df["service_date"].min(), cfg.LAST_DATE)
    out = pd.DataFrame(index=days)
    out["rows"] = df.groupby("service_date").size().reindex(days, fill_value=0)
    lo, hi = (pd.Timestamp(d) for d in cfg.SOURCE_GAP)
    out["in_source_gap"] = (out.index >= lo) & (out.index <= hi)
    out["observed"] = out["rows"] > 0
    return out


def build_grid(df: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """Full real-weekday x (stop, time of day) grid. Rows of missing days are kept with NaN targets."""
    days = real_weekdays(calendar, df["service_date"].min(), cfg.LAST_DATE)
    units = df[UNIT].drop_duplicates()
    grid = (pd.DataFrame({"service_date": days}).merge(units, how="cross"))
    obs = df[UNIT + ["service_date", "deviation", "late_5min", "early_60s"]]
    grid = grid.merge(obs, on=UNIT + ["service_date"], how="left", validate="one_to_one")
    observed_days = set(df["service_date"])
    grid["is_missing_day"] = ~grid["service_date"].isin(observed_days)
    grid["is_missing_row"] = grid["deviation"].isna()
    return grid


def carry_forward_ridership(df: pd.DataFrame, ridership: pd.DataFrame) -> pd.DataFrame:
    """Fill ridership for dates after the last published period with that period's values, and flag them."""
    out = df.copy()
    last = ridership.loc[ridership["period_end"].idxmax(), "schedule_period_name"]
    missing = out["average_boardings"].isna()
    out["ridership_carried_forward"] = missing.astype(int)
    r = ridership[ridership["schedule_period_name"] == last].set_index(["stop_number", "time_period"])
    key = pd.MultiIndex.from_frame(out.loc[missing, ["stop_number", "time_period"]])
    for col in RIDERSHIP_FEATURES:
        out.loc[missing, col] = r[col].reindex(key).values
    out.loc[missing, "schedule_period_name"] = last
    return out


# ================================================================ 7. modelling table
KEY_COLUMNS = ["service_date", "scheduled_time", "stop_number", "time_of_day"]
TARGETS = ["late_5min", "early_60s"]


def modelling_columns(df: pd.DataFrame) -> list[str]:
    feats = (["hour", "minute", "minute_of_day", "day_of_week", "month",
              "stop_lon", "stop_lat", "stop_order", "time_period", "schedule_period_name"]
             + [c for c in df.columns if c.startswith(("hist_", "route_prev_"))]
             + ["days_since_last_observed"]
             + [c for c in df.columns if c.startswith("wx_prev_")]
             + CALENDAR_FEATURES + RIDERSHIP_FEATURES + ["ridership_carried_forward"]
             + [c for c in df.columns if c.startswith("z_")])
    return KEY_COLUMNS + ["deviation"] + TARGETS + [c for c in feats if c in df.columns]


def prepare(tables: dict[str, pd.DataFrame] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run every step in notebook order. Returns (modelling table, scaler statistics)."""
    t = tables or load_all()
    df, weather, calendar, ridership = t["main"], t["weather"], t["calendar"], t["ridership"]
    df = parse_times(df)
    df = drop_conflicting_duplicates(df)
    df = drop_extreme_deviation(df)
    df = keep_real_weekdays(df, calendar)
    check_side_tables(weather, calendar, ridership, df)
    df = add_calendar_features(df)
    df = add_targets(df)
    df = add_stop_coordinates(df)
    df = add_history_features(df, calendar)
    df = join_weather(df, weather)
    df = join_calendar(df, calendar)
    df = join_ridership(df, ridership)
    df = carry_forward_ridership(df, ridership)
    stats = fit_scaler(df, numeric_features(df))
    df = apply_scaler(df, stats)
    return df[modelling_columns(df)].reset_index(drop=True), stats
