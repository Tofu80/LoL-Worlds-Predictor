import pandas as pd


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
    decay_half_life_days: int,
) -> dict[str, float]:
    # TIME-DECAY APPROACH: two options to discuss with Phu before implementing:
    #   A) Scale K by exp(-ln2 * age_days / half_life) when replaying each game.
    #   B) Decay each team's rating toward initial_rating between gaps in play.
    # Option A is more common in sports models. Raise before implementing.
    raise NotImplementedError("Time-decay Elo formula not yet decided — see comment above")
