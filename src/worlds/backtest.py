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
PREDICTION_COLUMNS = [
    "gameid",
    "date",
    "blue",
    "red",
    "p_blue",
    "result",
    "blue_league",
    "red_league",
]
INGEST_CONFIG_PATH = Path("config/ingest.yaml")


@dataclass
class BacktestResult:
    log_loss: float
    brier: float
    n_games: int
    calibration: pd.DataFrame
    odds_log_loss: float | None  # None when no betting-odds data
    predictions: (
        pd.DataFrame
    )  # PREDICTION_COLUMNS; result 1 = blue won; league = key at prediction time
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
    state = elo.replay(games, cutoff_date, config)
    ratings = state.team
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
                rows.append(
                    (
                        g.gameid,
                        g.date,
                        g.blue,
                        g.red,
                        state.p_blue(g.blue, g.red),
                        g.result,
                        state.member.get(g.blue),
                        state.member.get(g.red),
                    )
                )
        if mode == "in_tournament":
            for g in group.itertuples(index=False):
                state.update(g.blue, g.red, g.league, bool(g.result == 1), k)
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


def per_game_loss(p, y) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def bootstrap_diff(
    loss_a, loss_b, n: int, rng: np.random.Generator
) -> tuple[float, float, float]:
    """Paired bootstrap of mean(loss_a - loss_b): resample games, 95% percentile CI.

    Returns (mean difference, low, high). Negative means a is better.
    """
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    means = d[rng.integers(0, len(d), size=(n, len(d)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(d.mean()), float(lo), float(hi)


def matchup_class(blue_league, red_league, major: list[str]) -> str:
    """same-league / major-major / major-minor / minor-minor by league key at prediction time."""
    if blue_league is None or red_league is None:
        return "unknown"
    if blue_league == red_league:
        return "same-league"
    n_major = (blue_league in major) + (red_league in major)
    return ("minor-minor", "major-minor", "major-major")[n_major]


def run_years(games: pd.DataFrame, config: dict) -> dict[int, BacktestResult]:
    return {
        year: backtest_worlds(year, games, config, pd.Timestamp(t["start_date"]))
        for year, t in config["tournaments"].items()
    }


def _pool(results: dict[int, BacktestResult], years=None) -> pd.DataFrame:
    return pd.concat(
        [r.predictions for y, r in results.items() if years is None or y in years]
    )


def _row(label: str, results: dict[int, BacktestResult] | None, pooled: BacktestResult):
    per_year = "".join(
        f"{results[y].log_loss:>9.4f}" if results else f"{'':>9}" for y in YEARS
    )
    return f"{label:<14}{per_year}{pooled.log_loss:>9.4f}{pooled.brier:>9.4f}"


YEARS = (2023, 2024, 2025)


def main() -> None:
    if not GAMES_PATH.exists():
        sys.exit(f"{GAMES_PATH} not found: run python -m worlds.ingest first")
    games = pd.read_parquet(GAMES_PATH)
    config = {
        **yaml.safe_load(ELO_CONFIG_PATH.read_text()),
        **yaml.safe_load(BACKTEST_CONFIG_PATH.read_text()),
        "international_leagues": yaml.safe_load(INGEST_CONFIG_PATH.read_text())[
            "international_leagues"
        ],
    }
    off = {**config, "side_advantage": "none", "league_offsets": "off"}
    plus_h = {**off, "side_advantage": "pre_cutoff_rate"}

    # k_league grid: 2023-24 only (merge bar C), with H on.
    grid = {}
    for k_league in config["k_league_grid"]:
        res = run_years(games, {**plus_h, "league_offsets": "on", "k_league": k_league})
        grid[k_league] = log_loss(
            _pool(res, (2023, 2024))["p_blue"], _pool(res, (2023, 2024))["result"]
        )
    best_k = min(grid, key=grid.get)
    print("k_league grid, pooled 2023-24 log loss (+H +league):")
    for k_league, ll in grid.items():
        print(
            f"  k_league={k_league:<4}{ll:.4f}"
            + ("  <- chosen" if k_league == best_k else "")
        )

    if best_k != config["k_league"]:
        warnings.warn(
            f"grid picks k_league={best_k} but config/elo.yaml has {config['k_league']}",
            stacklevel=2,
        )
    full = {**plus_h, "league_offsets": "on", "k_league": best_k}
    runs = {
        "current": run_years(games, off),
        "+H": run_years(games, plus_h),
        "+H+league": run_years(games, full),
    }
    pooled = {name: score(_pool(r)) for name, r in runs.items()}

    base = _pool(runs["current"])
    cutoffs = {
        y: pd.Timestamp(t["start_date"]) for y, t in config["tournaments"].items()
    }
    blue_p = np.array(
        [
            elo.expected_score(
                0.0,
                0.0,
                elo.blue_advantage(
                    games, cutoffs[d.year], config["side_advantage_window_days"]
                ),
            )
            for d in base["date"]
        ]
    )
    # a game's year is its Worlds year (WLDs games are scored in their own calendar year)
    blue_only_by_year = {
        y: score(
            runs["current"][y].predictions.assign(
                p_blue=blue_p[(base["date"].dt.year == y).to_numpy()]
            )
        )
        for y in YEARS
    }
    blue_only = score(base.assign(p_blue=blue_p))
    half = score(base.assign(p_blue=0.5))

    print(
        f"\n{'log loss':<14}"
        + "".join(f"{y:>9}" for y in YEARS)
        + f"{'pooled':>9}{'Brier':>9}"
    )
    for name, by_year in runs.items():
        print(_row(name, by_year, pooled[name]))
    print(_row("blue-only", blue_only_by_year, blue_only))
    print(_row("0.5", None, half))

    rng = np.random.default_rng(config["random_seed"])
    cur = per_game_loss(base["p_blue"], base["result"])
    print(
        "\nPaired bootstrap of pooled log loss difference vs current (negative = better):"
    )
    for name in ("+H", "+H+league"):
        pr = _pool(runs[name])
        if not (pr["gameid"].to_numpy() == base["gameid"].to_numpy()).all():
            raise ValueError(f"{name} and current score different games")
        m, lo, hi = bootstrap_diff(
            per_game_loss(pr["p_blue"], pr["result"]),
            cur,
            config["bootstrap_samples"],
            rng,
        )
        print(f"  {name:<10}{m:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")

    cur_ll = pooled["current"].log_loss
    y25_cur = runs["current"][2025].log_loss
    ok = (
        pooled["+H+league"].log_loss < cur_ll
        and runs["+H+league"][2025].log_loss <= y25_cur
    )
    print(
        f"\nMerge bar (+H+league, k_league={best_k}): pooled {pooled['+H+league'].log_loss:.4f} < "
        f"{cur_ll:.4f} and 2025 {runs['+H+league'][2025].log_loss:.4f} <= {y25_cur:.4f}: "
        + ("PASS" if ok else "FAIL")
    )

    # Calibration by matchup class; the class comes from the +H+league run's league keys.
    lg = _pool(runs["+H+league"])
    cls = {
        g: matchup_class(b, r, config["major_leagues"])
        for g, b, r in zip(lg["gameid"], lg["blue_league"], lg["red_league"])
    }
    for name in ("current", "+H+league"):
        pr = _pool(runs[name]).assign(cls=lambda d: d["gameid"].map(cls))
        print(f"\nFavourite's view by matchup class ({name}):")
        print(
            f"  {'class':<13}{'n':>5}{'mean_pred':>11}{'observed':>10}{'log loss':>10}"
        )
        for c in (
            "same-league",
            "major-major",
            "major-minor",
            "minor-minor",
            "unknown",
        ):
            sub = pr[pr["cls"] == c]
            if sub.empty:
                continue
            t = calibration_table(sub["p_blue"], sub["result"])
            n = t["n"].sum()
            pred = np.nansum(t["n"] * t["mean_pred"]) / n
            obs = np.nansum(t["n"] * t["observed"]) / n
            print(
                f"  {c:<13}{n:>5}{pred:>11.3f}{obs:>10.3f}{log_loss(sub['p_blue'], sub['result']):>10.4f}"
            )

    prestart = {y: r.n_prestart_wlds for y, r in runs["current"].items()}
    print()
    for year, n in prestart.items():
        print(
            f"{year}: {n} WLDs games before start_date {config['tournaments'][year]['start_date']} "
            "(qualifiers, rating data only, not scored)"
        )


if __name__ == "__main__":
    main()
