import math
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from worlds import elo

GAMES_PATH = Path("data/processed/games.parquet")
ELO_CONFIG_PATH = Path("config/elo.yaml")
BACKTEST_CONFIG_PATH = Path("config/backtest.yaml")
RATING_UPDATES = ("in_tournament", "frozen")
EPS = 1e-15
BIN_EDGES = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
PREDICTION_COLUMNS = ["gameid", "date", "blue", "red", "p_blue", "result"]


@dataclass
class BacktestResult:
    log_loss: float
    brier: float
    n_games: int
    calibration: pd.DataFrame
    odds_log_loss: float | None  # None when no betting-odds data
    predictions: pd.DataFrame  # gameid, date, blue, red, p_blue, result (1 = blue won)
    n_prestart_wlds: int = (
        0  # same-year WLDs games before start_date: rated, not scored
    )


def log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y) -> float:
    return float(
        np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2)
    )


def calibration_table(p, y) -> pd.DataFrame:
    """Favourite's view: bins [0.5,0.6) ... [0.9,1.0]; n, mean predicted, observed win rate."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    fav = np.maximum(p, 1 - p)
    won = np.where(p >= 0.5, y, 1 - y)
    # Last bin is closed on the right, so p == 1.0 is counted.
    idx = np.minimum(np.digitize(fav, BIN_EDGES[1:-1]), len(BIN_EDGES) - 2)
    rows = []
    for i in range(len(BIN_EDGES) - 1):
        m = idx == i
        rows.append(
            {
                "bin": f"[{BIN_EDGES[i]:.1f}, {BIN_EDGES[i + 1]:.1f}"
                + ("]" if i == len(BIN_EDGES) - 2 else ")"),
                "n": int(m.sum()),
                "mean_pred": float(fav[m].mean()) if m.any() else float("nan"),
                "observed": float(won[m].mean()) if m.any() else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def score(predictions: pd.DataFrame) -> BacktestResult:
    p, y = predictions["p_blue"], predictions["result"]
    return BacktestResult(
        log_loss=log_loss(p, y),
        brier=brier(p, y),
        n_games=len(predictions),
        calibration=calibration_table(p, y),
        odds_log_loss=None,
        predictions=predictions.reset_index(drop=True),
    )


def _blue_red(games: pd.DataFrame) -> pd.DataFrame:
    """One row per game: gameid, date, league, blue, red, result (1 = blue won)."""
    blue = games[games["side"] == "Blue"].set_index("gameid")
    red = games[games["side"] == "Red"].set_index("gameid")
    if (
        blue.index.has_duplicates
        or red.index.has_duplicates
        or set(blue.index) != set(red.index)
        or len(blue) + len(red) != len(games)
    ):
        raise ValueError("every gameid needs exactly one Blue and one Red row")
    return pd.DataFrame(
        {
            "date": blue["date"],
            "league": blue["league"],
            "blue": blue["teamname"],
            "red": red["teamname"],
            "result": blue["result"],
        }
    ).reset_index()


def backtest_worlds(
    year: int,
    games: pd.DataFrame,
    config: dict,
    cutoff_date: pd.Timestamp,
) -> BacktestResult:
    """Backtest one Worlds starting at cutoff_date.

    Ratings start from games with date < cutoff_date. With
    rating_updates == "in_tournament", each Worlds game is predicted from
    games strictly before it, then added to the ratings; with "frozen",
    ratings stay fixed at cutoff_date.

    Evaluated: league == "WLDs", date >= config start_date, same calendar year.
    Other games from cutoff_date on (qualifiers, other leagues) update ratings
    but are not scored. Games sharing a timestamp are all predicted before any
    of them updates the ratings. cutoff_date must be <= start_date, otherwise a
    scored game's own result would already be in the starting ratings.
    """
    mode = config["rating_updates"]
    if mode not in RATING_UPDATES:
        raise ValueError(
            f"rating_updates must be one of {RATING_UPDATES}, got {mode!r}"
        )
    start = pd.Timestamp(config["tournaments"][year]["start_date"])
    if cutoff_date > start:
        raise ValueError(
            f"cutoff_date {cutoff_date} is after the {year} start_date {start}"
        )

    k, initial = config["k_factor"], float(config["initial_rating"])
    ratings = elo.compute_ratings(
        games,
        cutoff_date,
        k,
        initial,
        config["decay_half_life_days"],
        config["decay_method"],
    )
    table = _blue_red(games)
    scored = (
        (table["league"] == "WLDs")
        & (table["date"] >= start)
        & (table["date"].dt.year == year)
    )
    if not scored.any():
        raise ValueError(f"no WLDs games on or after {start} in {year}")
    rated = set(ratings)
    unseen = sorted(
        {
            t
            for t in table.loc[scored, ["blue", "red"]].to_numpy().ravel()
            if t not in rated
        }
    )
    if unseen:
        warnings.warn(
            f"{year}: scored teams with no games before {cutoff_date} start at "
            f"{initial:.0f} (check the alias table): {unseen}",
            stacklevel=2,
        )
    last = table.loc[scored, "date"].max()
    window = table[(table["date"] >= cutoff_date) & (table["date"] <= last)]

    rows = []
    for _, group in window.sort_values(["date", "gameid"]).groupby("date", sort=True):
        for g in group.itertuples(index=False):
            if _is_scored(g, start, year):
                rb = ratings.get(g.blue, initial)
                rr = ratings.get(g.red, initial)
                rows.append(
                    (
                        g.gameid,
                        g.date,
                        g.blue,
                        g.red,
                        elo.expected_score(rb, rr),
                        g.result,
                    )
                )
        if mode == "in_tournament":
            for g in group.itertuples(index=False):
                rb = ratings.setdefault(g.blue, initial)
                rr = ratings.setdefault(g.red, initial)
                ratings[g.blue], ratings[g.red] = elo.update_ratings(
                    rb, rr, float(g.result), k
                )
    result = score(pd.DataFrame(rows, columns=PREDICTION_COLUMNS))
    result.n_prestart_wlds = int(
        (
            (table["league"] == "WLDs")
            & (table["date"] < start)
            & (table["date"].dt.year == year)
        ).sum()
    )
    return result


def _is_scored(g, start: pd.Timestamp, year: int) -> bool:
    return g.league == "WLDs" and g.date >= start and g.date.year == year


def _fmt(label: str, year: object, r: BacktestResult) -> str:
    return f"{label:<14}{year!s:<8}{r.n_games:>5}{r.log_loss:>10.4f}{r.brier:>9.4f}"


def main() -> None:
    if not GAMES_PATH.exists():
        sys.exit(f"{GAMES_PATH} not found: run python -m worlds.ingest first")
    games = pd.read_parquet(GAMES_PATH)
    config = {
        **yaml.safe_load(ELO_CONFIG_PATH.read_text()),
        **yaml.safe_load(BACKTEST_CONFIG_PATH.read_text()),
    }
    print(f"{'mode':<14}{'year':<8}{'n':>5}{'log loss':>10}{'Brier':>9}")
    pooled_by_mode = {}
    prestart = {}
    for mode in RATING_UPDATES:
        cfg = {**config, "rating_updates": mode}
        parts = []
        for year, t in config["tournaments"].items():
            r = backtest_worlds(year, games, cfg, pd.Timestamp(t["start_date"]))
            parts.append(r.predictions)
            prestart[year] = r.n_prestart_wlds  # same in both modes
            print(_fmt(mode, year, r))
        pooled_by_mode[mode] = score(pd.concat(parts))
        print(_fmt(mode, "pooled", pooled_by_mode[mode]))
    print(f"{'0.5 baseline':<14}{'':<8}{'':>5}{math.log(2):>10.4f}{0.25:>9.4f}")
    print()
    for year, n in prestart.items():
        start = config["tournaments"][year]["start_date"]
        print(
            f"{year}: {n} WLDs games before start_date {start} "
            "(qualifiers, rating data only, not scored)"
        )
    chosen = config["rating_updates"]
    print(f"\nPooled calibration ({chosen}), favourite's view:")
    print(
        pooled_by_mode[chosen].calibration.to_string(index=False, float_format="%.3f")
    )


if __name__ == "__main__":
    main()
