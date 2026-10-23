import math

import pandas as pd

# Planned third option: Option B regress-to-mean (parked).
DECAY_METHODS = ("k_scale", "none")


def decay_weight(age_days: float, half_life_days: float) -> float:
    """Exponential decay: 1 at age 0, halving every half_life_days."""
    return math.exp(-math.log(2) * age_days / half_life_days)


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def update_ratings(
    rating_a: float,
    rating_b: float,
    result: float,
    k: float,
) -> tuple[float, float]:
    ea = expected_score(rating_a, rating_b)
    new_a = rating_a + k * (result - ea)
    new_b = rating_b + k * ((1 - result) - (1 - ea))
    return new_a, new_b


def compute_ratings(
    games: pd.DataFrame,
    cutoff_date: pd.Timestamp,
    k: float,
    initial_rating: float,
    decay_half_life_days: float,
    decay_method: str,
) -> dict[str, float]:
    """Replay games dated strictly before cutoff_date; return {teamname: rating}.

    games: team rows as returned by ingest.load_games (two rows per gameid,
    with columns gameid, date, teamname, side, result). Games are replayed in
    (date, gameid) order. New teams start at initial_rating.

    decay_method:
      k_scale: each game's K is multiplied by decay_weight(age_days, half-life),
               where age_days = (cutoff_date - game date) in fractional days.
               Age is measured from cutoff_date, not from today and not from
               each later game, so one replay gives the ratings at cutoff_date.
      none:    weight 1 (plain Elo), the no-decay baseline.
    Both teams in a game use the same scaled K, so every update is zero-sum.

    Games on or after cutoff_date are ignored. In the backtest, in-tournament
    games are added afterwards with update_ratings at full K (age 0).

    Raises ValueError for an unknown decay_method, or if any gameid in games
    (before or after the cutoff) doesn't have exactly two rows with one win.
    """
    if decay_method not in DECAY_METHODS:
        raise ValueError(
            f"decay_method must be one of {DECAY_METHODS}, got {decay_method!r}"
        )

    # Two rows with min 0 and max 1 means exactly one win and one loss.
    per_game = games.groupby("gameid")["result"].agg(["size", "min", "max"])
    ok = (per_game["size"] == 2) & (per_game["min"] == 0) & (per_game["max"] == 1)
    bad = per_game.index[~ok]
    if len(bad):
        raise ValueError(
            f"gameids without exactly two rows and one win: {list(bad[:10])}"
        )

    past = games[games["date"] < cutoff_date]
    winners = past.loc[past["result"] == 1, ["gameid", "date", "teamname"]]
    losers = past.loc[past["result"] == 0, ["gameid", "teamname"]]
    pairs = winners.merge(losers, on="gameid", suffixes=("_w", "_l")).sort_values(
        ["date", "gameid"]
    )

    ratings: dict[str, float] = {}
    for game in pairs.itertuples(index=False):
        rw = ratings.setdefault(game.teamname_w, float(initial_rating))
        rl = ratings.setdefault(game.teamname_l, float(initial_rating))
        weight = 1.0
        if decay_method == "k_scale":
            age_days = (cutoff_date - game.date) / pd.Timedelta(days=1)
            weight = decay_weight(age_days, decay_half_life_days)
        ratings[game.teamname_w], ratings[game.teamname_l] = update_ratings(
            rw, rl, 1.0, k * weight
        )
    return ratings
