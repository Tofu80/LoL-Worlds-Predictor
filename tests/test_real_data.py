"""Checks against the real Oracle's Elixir files; skipped when they aren't downloaded."""

from pathlib import Path

import pandas as pd
import pytest
import yaml

RAW = Path("data/raw")
CFG = yaml.safe_load(Path("config/backtest.yaml").read_text())


def wlds_dates(year: int) -> pd.Series:
    path = RAW / f"{year}_LoL_esports_match_data_from_OraclesElixir.csv"
    if not path.exists():
        pytest.skip(f"{path} not downloaded")
    df = pd.read_csv(path, usecols=["league", "date", "position"])
    team = df[(df["position"] == "team") & (df["league"] == "WLDs")]
    return pd.to_datetime(team["date"], format="ISO8601")


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_first_wlds_game_on_or_after_start_date_is_on_that_day(year):
    start = pd.Timestamp(CFG["tournaments"][year]["start_date"])
    dates = wlds_dates(year)
    first = dates[dates >= start].min()
    assert first.normalize() == start  # play-in opens on start_date (UTC)


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_wlds_games_before_start_date_exist_as_qualifier_rating_data(year):
    start = pd.Timestamp(CFG["tournaments"][year]["start_date"])
    dates = wlds_dates(year)
    assert (dates < start).any()  # qualifiers: kept as rating data, not evaluated
