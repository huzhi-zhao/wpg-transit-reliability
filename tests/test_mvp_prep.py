"""Tests for notebooks/mvp_prep.py: no leakage, joins keep the row count, cleaning rules hold.

Run from the repository root:
    uv run --with pytest --with pandas --with pyarrow pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "notebooks"))

import mvp_config as cfg  # noqa: E402
import mvp_prep as prep  # noqa: E402


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def tables():
    return prep.load_all()


@pytest.fixture(scope="module")
def cleaned(tables):
    """Main table after section 3, before any feature or join."""
    df = prep.parse_times(tables["main"])
    df = prep.drop_conflicting_duplicates(df)
    df = prep.drop_extreme_deviation(df)
    return prep.keep_real_weekdays(df, tables["calendar"])


@pytest.fixture(scope="module")
def featured(cleaned, tables):
    """After the main-table features of section 4 (4.1-4.4), before the side-table joins."""
    df = prep.add_calendar_features(cleaned)
    df = prep.add_targets(df)
    df = prep.add_stop_coordinates(df)
    return prep.add_history_features(df, tables["calendar"])


@pytest.fixture(scope="module")
def prepared(tables):
    return prep.prepare(tables)


# ---------------------------------------------------------------- cleaning (section 3)
def test_cleaning_row_counts(tables, cleaned):
    assert len(tables["main"]) == 80_032
    assert len(cleaned) == 79_576
    assert cleaned["service_date"].nunique() == 268


def test_conflicting_duplicates_drop_every_copy():
    t = pd.Timestamp("2026-01-05 08:00:00")
    df = pd.DataFrame({"stop_number": ["1", "1", "2"], "scheduled_time": [t, t, t], "deviation": [10, -500, 0]})
    out = prep.drop_conflicting_duplicates(df)
    assert out["stop_number"].tolist() == ["2"]


def test_extreme_deviation_rule():
    df = pd.DataFrame({"deviation": [-3601, -3600, 0, 3600, 3601]})
    assert prep.drop_extreme_deviation(df)["deviation"].tolist() == [-3600, 0, 3600]


def test_only_real_weekdays_remain(cleaned, tables):
    holidays = set(tables["calendar"].loc[tables["calendar"]["is_holiday"], "date"])
    assert (cleaned["service_date"].dt.day_of_week < 5).all()
    assert not cleaned["service_date"].isin(holidays).any()
    assert not cleaned.duplicated(["stop_number", "scheduled_time"]).any()


def test_side_tables_are_joinable(tables, cleaned):
    periods = prep.check_side_tables(tables["weather"], tables["calendar"], tables["ridership"], cleaned)
    assert len(periods) == 5


# ---------------------------------------------------------------- targets
def test_targets_follow_thresholds(featured):
    assert featured["late_5min"].eq(featured["deviation"] < -cfg.LATE_S).all()
    assert featured["early_60s"].eq(featured["deviation"] > cfg.EARLY_S).all()
    assert not (featured["late_5min"] & featured["early_60s"]).any()


# ---------------------------------------------------------------- leakage (section 4.4)
def test_history_matches_brute_force_on_earlier_days(featured):
    """Recompute history features of random rows from strictly earlier service days only."""
    df = featured
    rng = np.random.default_rng(1)
    for i in rng.choice(len(df), 200, replace=False):
        r = df.iloc[i]
        unit = df[(df["stop_number"] == r["stop_number"]) & (df["time_of_day"] == r["time_of_day"])]
        past = unit[unit["service_date"] < r["service_date"]].sort_values("service_date")
        for n in cfg.LAG_WINDOWS:
            for target, short in [("late_5min", "late"), ("early_60s", "early")]:
                tail = past[target].tail(n)
                expected = tail.mean() if len(tail) >= cfg.LAG_MIN_OBS[n] else np.nan
                got = r[f"hist_{short}_{n}d"]
                assert (np.isnan(expected) and np.isnan(got)) or got == pytest.approx(expected)
        earlier = df[df["service_date"] < r["service_date"]]
        if len(earlier):
            last_day = df[df["service_date"] == earlier["service_date"].max()]
            assert r["route_prev_late"] == pytest.approx(last_day["late_5min"].mean())
            assert r["route_prev_early"] == pytest.approx(last_day["early_60s"].mean())
        else:
            assert np.isnan(r["route_prev_late"])


def test_changing_a_day_does_not_change_its_own_or_earlier_features(featured, tables):
    """Flip every target on one day: features of that day and of all earlier days must not move."""
    hist_cols = [c for c in featured.columns if c.startswith(("hist_", "route_prev_"))] + ["days_since_last_observed"]
    base = featured.drop(columns=hist_cols)
    day = featured["service_date"].sort_values().unique()[150]

    flipped = base.copy()
    on_day = flipped["service_date"] == day
    flipped.loc[on_day, "late_5min"] = ~flipped.loc[on_day, "late_5min"]
    flipped.loc[on_day, "early_60s"] = ~flipped.loc[on_day, "early_60s"]

    a = prep.add_history_features(base, tables["calendar"])
    b = prep.add_history_features(flipped, tables["calendar"])
    upto = a["service_date"] <= day
    pd.testing.assert_frame_equal(a.loc[upto, hist_cols], b.loc[upto, hist_cols])
    assert not a.loc[~upto, hist_cols].equals(b.loc[~upto, hist_cols])   # later days do see it


def test_days_since_last_observed(featured):
    assert featured["days_since_last_observed"].dropna().ge(1).all()
    first_day = featured["service_date"].min()
    assert featured.loc[featured["service_date"] == first_day, "days_since_last_observed"].isna().all()


# ---------------------------------------------------------------- joins (sections 4.5-4.7)
def test_joins_keep_row_count(featured, tables):
    n = len(featured)
    df = prep.join_weather(featured, tables["weather"])
    assert len(df) == n
    df = prep.join_calendar(df, tables["calendar"])
    assert len(df) == n
    df = prep.join_ridership(df, tables["ridership"])
    assert len(df) == n
    df = prep.carry_forward_ridership(df, tables["ridership"])
    assert len(df) == n
    assert not df.duplicated(["stop_number", "scheduled_time"]).any()


def test_weather_is_from_the_previous_day(featured, tables):
    df = prep.join_weather(featured, tables["weather"])
    w = tables["weather"].set_index("date")["temperature_2m_max"]
    expected = (df["service_date"] - pd.Timedelta(days=1)).map(w)
    assert df["wx_prev_temperature_2m_max"].eq(expected).all()
    groups = df.filter(like="wx_prev_is_")
    assert groups.sum(axis=1).eq(1).all()          # exactly one weather group per row


def test_time_period_boundaries():
    hours = pd.Series([0, 8, 9, 14, 15, 17, 18, 23])
    assert prep.time_period(hours).tolist() == [
        "Morning", "Morning", "Mid-Day", "Mid-Day", "PM Peak", "PM Peak", "Evening", "Evening"]


def test_ridership_gap_is_filled_and_flagged(featured, tables):
    df = prep.join_ridership(featured, tables["ridership"])
    gap = df["average_boardings"].isna()
    assert gap.any()
    assert df.loc[gap, "service_date"].min() > tables["ridership"]["period_end"].max()
    out = prep.carry_forward_ridership(df, tables["ridership"])
    assert out[prep.RIDERSHIP_FEATURES].notna().all().all()
    assert out["ridership_carried_forward"].eq(gap.astype(int)).all()


# ---------------------------------------------------------------- standardization (section 5)
def test_scaler_uses_training_rows_only(prepared):
    df, stats = prepared
    train = df["service_date"] <= pd.Timestamp(cfg.TRAIN_END)
    for col in stats.index:
        z = df.loc[train, f"z_{col}"].dropna()
        assert z.mean() == pytest.approx(0, abs=1e-9)
        assert z.std(ddof=0) == pytest.approx(1, abs=1e-9)

    # Changing rows after TRAIN_END must not change the fitted statistics.
    later = df.copy()
    later.loc[~train, stats.index] = later.loc[~train, stats.index] * 10 + 5
    pd.testing.assert_frame_equal(stats, prep.fit_scaler(later, list(stats.index)))


# ---------------------------------------------------------------- modelling table (section 7)
def test_modelling_table_shape_and_keys(prepared):
    df, _ = prepared
    assert df.shape == (79_576, 62)
    assert not df.duplicated(["stop_number", "scheduled_time"]).any()
    assert df[prep.TARGETS].notna().all().all()
    # Only history features may be empty (start of the series); everything else is filled.
    empty = df.columns[df.isna().any()]
    assert all(c.startswith(("hist_", "route_prev_", "days_since", "z_hist_", "z_route_prev_", "z_days_since"))
               for c in empty), list(empty)


def test_saved_table_matches_prepare(prepared):
    if not cfg.PREPARED_PATH.exists():
        pytest.skip("run the notebook first to write the prepared table")
    saved = pd.read_parquet(cfg.PREPARED_PATH)
    pd.testing.assert_frame_equal(saved, prepared[0], check_dtype=False)
