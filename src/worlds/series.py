from functools import cache

import pandas as pd

from worlds.elo import expected_score


def bo3_win_prob(p: float) -> float:
    return p**2 * (3 - 2 * p)


def bo5_win_prob(p: float) -> float:
    return p**3 * (10 - 15 * p + 6 * p**2)


def series_win_prob(p: float, format: str) -> float:
    match format.lower():
        case "bo1":
            return p
        case "bo3":
            return bo3_win_prob(p)
        case "bo5":
            return bo5_win_prob(p)
        case _:
            raise ValueError(f"Unknown series format: {format!r}")


def bo5_rofs_win_prob(
    strength_a: float, strength_b: float, h: float, q: float, game1_qa: float
) -> float:
    """P(A wins a Bo5) when the side of each game follows Right of First Selection.

    q: probability that the RoFS holder (the previous game's loser) ends up on blue.
    game1_qa: A's probability of being blue in game 1 (q, 1 - q or 0.5).
    Game k+1: A is blue with probability q if A lost game k, else 1 - q. Per game,
    p_A = q_A * E(sA + H, sB) + (1 - q_A) * E(sA, sB + H). State = (wins A, wins B,
    previous loser), so it is exact; with q = 0.5 or H = 0 it reduces to bo5_win_prob.
    """
    win_blue = expected_score(strength_a, strength_b, h)  # A on blue
    win_red = expected_score(strength_a, strength_b, -h)  # A on red

    @cache
    def go(a: int, b: int, prev_loser: str | None) -> float:
        if a == 3:
            return 1.0
        if b == 3:
            return 0.0
        q_a = game1_qa if prev_loser is None else (q if prev_loser == "A" else 1 - q)
        p_a = q_a * win_blue + (1 - q_a) * win_red
        return p_a * go(a + 1, b, "B") + (1 - p_a) * go(a, b + 1, "A")

    return go(0, 0, None)


def rofs_q(
    games: pd.DataFrame, cutoff_date: pd.Timestamp, leagues: list[str], gap_hours: float
) -> tuple[float, int]:
    """Share of games 2+ where the previous game's loser played blue, and how many.

    Uses only games with date < cutoff_date, in `leagues`, in the calendar year of
    cutoff_date. A game is game 2+ if the same two teams played the game before it
    less than gap_hours earlier. games: team rows (gameid, date, league, teamname,
    side, result). Raises ValueError if no game 2+ exists.
    """
    g = games[
        (games["date"] < cutoff_date)
        & (games["date"].dt.year == cutoff_date.year)
        & (games["league"].isin(leagues))
    ]
    blue = g[g["side"] == "Blue"].set_index("gameid")
    red = g[g["side"] == "Red"].set_index("gameid")
    t = pd.DataFrame(
        {
            "date": blue["date"],
            "blue": blue["teamname"],
            "red": red["teamname"],
            "blue_won": blue["result"] == 1,
        }
    ).reset_index()
    t["pair"] = [frozenset(x) for x in zip(t["blue"], t["red"])]
    t["loser"] = t["red"].where(t["blue_won"], t["blue"])
    t = t.sort_values(["date", "gameid"])
    prev = t.groupby("pair")[["date", "loser"]].shift(1)
    cont = (t["date"] - prev["date"]) < pd.Timedelta(hours=gap_hours)
    n = int(cont.sum())
    if n == 0:
        raise ValueError("no game 2+ found before the cutoff to estimate q")
    return float((t.loc[cont, "blue"] == prev.loc[cont, "loser"]).mean()), n
