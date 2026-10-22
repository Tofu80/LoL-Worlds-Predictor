from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestResult:
    log_loss: float
    brier: float
    n_games: int
    calibration: pd.DataFrame
    odds_log_loss: float | None  # None when no betting-odds data


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
    """
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError("backtest pipeline not wired yet")


if __name__ == "__main__":
    main()
