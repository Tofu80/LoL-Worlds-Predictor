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
    # Per-game rating snapshots (elo.EloState.history) when record=True, else None.
    history: pd.DataFrame | None = None


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
    record: bool = False,
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
    record=True also returns result.history: every game from the replay and the window,
    with each team's rating and league offset before and after (equal in frozen mode).
    It changes no prediction. history.scored marks the games in predictions; the rest
    are replay rows, qualifiers and other leagues. If one team plays two games with the
    same timestamp, the second row's rating_before includes the first (predictions do not).
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
    state = elo.replay(games, cutoff_date, config, record=record)
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
        for g in group.itertuples(index=False):
            if mode == "in_tournament":
                state.update(
                    g.blue,
                    g.red,
                    g.league,
                    bool(g.result == 1),
                    k,
                    gameid=g.gameid,
                    date=g.date,
                )
            else:
                state.observe(g.blue, g.red, g.gameid, g.date)
    result = score(pd.DataFrame(rows, columns=PREDICTION_COLUMNS))
    if record:
        result.history = pd.DataFrame(state.history)
        # replay rows (date < cutoff_date), qualifiers and other leagues are not scored
        result.history["scored"] = result.history["gameid"].isin(
            result.predictions["gameid"]
        )
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


def run_years(
    games: pd.DataFrame, config: dict, record: bool = False
) -> dict[int, BacktestResult]:
    return {
        year: backtest_worlds(
            year, games, config, pd.Timestamp(t["start_date"]), record=record
        )
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


CLASSES = ("same-league", "major-major", "major-minor", "minor-minor", "unknown")


def load_config() -> dict:
    return {
        **yaml.safe_load(ELO_CONFIG_PATH.read_text()),
        **yaml.safe_load(BACKTEST_CONFIG_PATH.read_text()),
        "international_leagues": yaml.safe_load(INGEST_CONFIG_PATH.read_text())[
            "international_leagues"
        ],
    }


def compare(games: pd.DataFrame, config: dict, record: bool = False) -> dict:
    """Every number main() prints, as a dict (the export reads this instead of re-deriving).

    keys: grid {k_league: pooled 2023-24 log loss}, best_k, runs {variant: {year:
    BacktestResult}}, pooled {variant: BacktestResult}, blue_only_by_year, blue_only,
    half, bootstrap {variant: (mean, lo, hi)} vs current, merge {ok, ...},
    by_class {variant: {class: (n, mean_pred, observed, log loss)}}, prestart.
    record=True also fills BacktestResult.history of the +H+league runs (the model).
    """
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

    full = {**plus_h, "league_offsets": "on", "k_league": best_k}
    runs = {
        "current": run_years(games, off),
        "+H": run_years(games, plus_h),
        "+H+league": run_years(games, full, record=record),
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

    rng = np.random.default_rng(config["random_seed"])
    cur = per_game_loss(base["p_blue"], base["result"])
    bootstrap = {}
    for name in ("+H", "+H+league"):
        pr = _pool(runs[name])
        if not (pr["gameid"].to_numpy() == base["gameid"].to_numpy()).all():
            raise ValueError(f"{name} and current score different games")
        bootstrap[name] = bootstrap_diff(
            per_game_loss(pr["p_blue"], pr["result"]),
            cur,
            config["bootstrap_samples"],
            rng,
        )

    cur_ll = pooled["current"].log_loss
    y25_cur = runs["current"][2025].log_loss
    merge = {
        "ok": pooled["+H+league"].log_loss < cur_ll
        and runs["+H+league"][2025].log_loss <= y25_cur,
        "pooled": pooled["+H+league"].log_loss,
        "current_pooled": cur_ll,
        "y2025": runs["+H+league"][2025].log_loss,
        "current_2025": y25_cur,
    }

    # Calibration by matchup class; the class comes from the +H+league run's league keys.
    lg = _pool(runs["+H+league"])
    cls = {
        g: matchup_class(b, r, config["major_leagues"])
        for g, b, r in zip(lg["gameid"], lg["blue_league"], lg["red_league"])
    }
    by_class = {}
    for name in ("current", "+H+league"):
        pr = _pool(runs[name]).assign(cls=lambda d: d["gameid"].map(cls))
        by_class[name] = {}
        for c in CLASSES:
            sub = pr[pr["cls"] == c]
            if sub.empty:
                continue
            t = calibration_table(sub["p_blue"], sub["result"])
            n = t["n"].sum()
            by_class[name][c] = (
                n,
                np.nansum(t["n"] * t["mean_pred"]) / n,
                np.nansum(t["n"] * t["observed"]) / n,
                log_loss(sub["p_blue"], sub["result"]),
            )

    return {
        "grid": grid,
        "best_k": best_k,
        "runs": runs,
        "pooled": pooled,
        "blue_only_by_year": blue_only_by_year,
        "blue_only": blue_only,
        "half": half,
        "bootstrap": bootstrap,
        "merge": merge,
        "by_class": by_class,
        "prestart": {y: r.n_prestart_wlds for y, r in runs["current"].items()},
    }


def main() -> None:
    if not GAMES_PATH.exists():
        sys.exit(f"{GAMES_PATH} not found: run python -m worlds.ingest first")
    games = pd.read_parquet(GAMES_PATH)
    config = load_config()
    c = compare(games, config)
    best_k = c["best_k"]

    print("k_league grid, pooled 2023-24 log loss (+H +league):")
    for k_league, ll in c["grid"].items():
        print(
            f"  k_league={k_league:<4}{ll:.4f}"
            + ("  <- chosen" if k_league == best_k else "")
        )
    if best_k != config["k_league"]:
        warnings.warn(
            f"grid picks k_league={best_k} but config/elo.yaml has {config['k_league']}",
            stacklevel=2,
        )

    print(
        f"\n{'log loss':<14}"
        + "".join(f"{y:>9}" for y in YEARS)
        + f"{'pooled':>9}{'Brier':>9}"
    )
    for name, by_year in c["runs"].items():
        print(_row(name, by_year, c["pooled"][name]))
    print(_row("blue-only", c["blue_only_by_year"], c["blue_only"]))
    print(_row("0.5", None, c["half"]))

    print(
        "\nPaired bootstrap of pooled log loss difference vs current (negative = better):"
    )
    for name, (m, lo, hi) in c["bootstrap"].items():
        print(f"  {name:<10}{m:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")

    mg = c["merge"]
    print(
        f"\nMerge bar (+H+league, k_league={best_k}): pooled {mg['pooled']:.4f} < "
        f"{mg['current_pooled']:.4f} and 2025 {mg['y2025']:.4f} <= {mg['current_2025']:.4f}: "
        + ("PASS" if mg["ok"] else "FAIL")
    )

    for name, rows in c["by_class"].items():
        print(f"\nFavourite's view by matchup class ({name}):")
        print(
            f"  {'class':<13}{'n':>5}{'mean_pred':>11}{'observed':>10}{'log loss':>10}"
        )
        for cls_name, (n, pred, obs, ll) in rows.items():
            print(f"  {cls_name:<13}{n:>5}{pred:>11.3f}{obs:>10.3f}{ll:>10.4f}")

    print()
    for year, n in c["prestart"].items():
        print(
            f"{year}: {n} WLDs games before start_date {config['tournaments'][year]['start_date']} "
            "(qualifiers, rating data only, not scored)"
        )


if __name__ == "__main__":
    main()
