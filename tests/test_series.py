import itertools

import pandas as pd
import pytest

from worlds.elo import expected_score
from worlds.series import (
    bo3_win_prob,
    bo5_rofs_win_prob,
    bo5_win_prob,
    rofs_q,
    series_win_prob,
)


def _brute_force_bo3(p: float) -> float:
    q = 1 - p
    return p**2 + 2 * p**2 * q  # win 2-0 + win 2-1


def _brute_force_bo5(p: float) -> float:
    q = 1 - p
    return p**3 + 3 * p**3 * q + 6 * p**3 * q**2  # win 3-0, 3-1, 3-2


def test_bo3_at_half():
    assert bo3_win_prob(0.5) == pytest.approx(0.5)


def test_bo5_at_half():
    assert bo5_win_prob(0.5) == pytest.approx(0.5)


def test_bo3_monotonic():
    assert bo3_win_prob(0.6) > bo3_win_prob(0.5) > bo3_win_prob(0.4)


def test_bo5_monotonic():
    assert bo5_win_prob(0.6) > bo5_win_prob(0.5) > bo5_win_prob(0.4)


@pytest.mark.parametrize("p", [0.3, 0.5, 0.7, 0.9])
def test_bo3_matches_brute_force(p: float):
    assert bo3_win_prob(p) == pytest.approx(_brute_force_bo3(p))


@pytest.mark.parametrize("p", [0.3, 0.5, 0.7, 0.9])
def test_bo5_matches_brute_force(p: float):
    assert bo5_win_prob(p) == pytest.approx(_brute_force_bo5(p))


def test_series_win_prob_bo1():
    assert series_win_prob(0.7, "bo1") == pytest.approx(0.7)


def test_series_win_prob_bo3():
    assert series_win_prob(0.7, "bo3") == pytest.approx(bo3_win_prob(0.7))


def test_series_win_prob_bo5():
    assert series_win_prob(0.7, "bo5") == pytest.approx(bo5_win_prob(0.7))


def test_series_win_prob_unknown_format():
    with pytest.raises(ValueError):
        series_win_prob(0.5, "bo7")


# ---- RoFS Bo5: the per-game win probability depends on who holds side choice ----


def _brute_force_rofs(sa, sb, h, q, game1_qa):
    """A wins the series iff A wins >= 3 of 5 hypothetical games (games after the
    decision sum to 1). Each game: A is blue with prob q_A (q if A lost the previous
    game, 1-q if B did, game1_qa in game 1), then the winner is drawn."""
    total = 0.0
    for path in itertools.product(
        [(True, True), (True, False), (False, True), (False, False)], repeat=5
    ):
        prob, a_wins, prev_loser = 1.0, 0, None
        for a_blue, a_won in path:
            q_a = (
                game1_qa if prev_loser is None else (q if prev_loser == "A" else 1 - q)
            )
            prob *= q_a if a_blue else 1 - q_a
            pa = expected_score(sa, sb, h) if a_blue else expected_score(sa, sb, -h)
            prob *= pa if a_won else 1 - pa
            a_wins += a_won
            prev_loser = "B" if a_won else "A"
        if a_wins >= 3:
            total += prob
    return total


@pytest.mark.parametrize("q", [0.0, 0.2, 0.5, 0.9])
@pytest.mark.parametrize("d", [-150.0, 0.0, 80.0])
def test_rofs_bo5_with_h_zero_equals_constant_p_formula(d, q):
    p = expected_score(1500 + d, 1500)
    for game1 in (0.5, q, 1 - q):
        assert bo5_rofs_win_prob(1500 + d, 1500, 0.0, q, game1) == pytest.approx(
            bo5_win_prob(p)
        )


@pytest.mark.parametrize("d", [-200.0, 0.0, 120.0])
@pytest.mark.parametrize("h", [0.0, 23.0, 60.0])
@pytest.mark.parametrize("q", [0.2, 0.5, 0.7])
@pytest.mark.parametrize("game1", ["q", "1-q", "half"])
def test_rofs_bo5_matches_brute_force(d, h, q, game1):
    g1 = {"q": q, "1-q": 1 - q, "half": 0.5}[game1]
    assert bo5_rofs_win_prob(1500 + d, 1500, h, q, g1) == pytest.approx(
        _brute_force_rofs(1500 + d, 1500, h, q, g1)
    )


def test_rofs_bo5_q_half_equals_side_neutral_average():
    sa, sb, h = 1560.0, 1500.0, 23.0
    avg = 0.5 * expected_score(sa, sb, h) + 0.5 * expected_score(sa, sb, -h)
    # with q = 0.5 every game has the same side-neutral probability
    assert bo5_rofs_win_prob(sa, sb, h, 0.5, 0.5) == pytest.approx(bo5_win_prob(avg))


def test_rofs_bo5_symmetry():
    a = bo5_rofs_win_prob(1560.0, 1500.0, 23.0, 0.2, 0.5)
    b = bo5_rofs_win_prob(1500.0, 1560.0, 23.0, 0.2, 0.5)
    assert a + b == pytest.approx(1.0)


def _rofs_games(rows):
    """rows: (gameid, date, league, blue, red, blue_won)."""
    out = []
    for gid, d, lg, blue, red, blue_won in rows:
        for side, team, won in (("Blue", blue, blue_won), ("Red", red, not blue_won)):
            out.append(
                {
                    "gameid": gid,
                    "date": pd.Timestamp(d),
                    "league": lg,
                    "teamname": team,
                    "side": side,
                    "result": int(won),
                }
            )
    return pd.DataFrame(out)


LEAGUES = ["LCK", "WLDs"]
CUT = pd.Timestamp("2026-11-02")
BASE_ROWS = [
    # series 1: A blue wins g1; g2 B (loser) is on blue -> counts 1; B blue wins g2;
    # g3 A (loser) is on red -> counts 0
    ("a1", "2026-10-01 10:00", "LCK", "A", "B", True),
    ("a2", "2026-10-01 11:00", "LCK", "B", "A", True),
    ("a3", "2026-10-01 12:00", "LCK", "B", "A", True),
    # a different series 5h later than a3 is not "game 2" of anything; game 1 only
    ("b1", "2026-10-02 10:00", "LCK", "C", "D", False),
    # game 2 of that series: C lost g1 and is blue again -> counts 1
    ("b2", "2026-10-02 11:00", "LCK", "C", "D", True),
    # excluded league
    ("x1", "2026-10-03 10:00", "LEC", "E", "F", True),
    ("x2", "2026-10-03 11:00", "LEC", "F", "E", True),
    # >= 4h gap: not a continuation
    ("c1", "2026-10-04 10:00", "LCK", "G", "H", True),
    ("c2", "2026-10-04 14:00", "LCK", "H", "G", True),
]


def test_rofs_q_hand_computed():
    q, n = rofs_q(_rofs_games(BASE_ROWS), CUT, LEAGUES, 4)
    # continuations: a2 (loser B blue: 1), a3 (loser A red: 0), b2 (loser C blue: 1)
    assert n == 3
    assert q == pytest.approx(2 / 3)


def test_rofs_q_ignores_games_on_or_after_cutoff_and_other_years():
    base = rofs_q(_rofs_games(BASE_ROWS), CUT, LEAGUES, 4)
    extra = BASE_ROWS + [
        ("z1", "2026-11-02 00:00", "LCK", "A", "B", True),
        ("z2", "2026-11-02 01:00", "LCK", "A", "B", False),
        ("z3", "2026-11-05 01:00", "LCK", "A", "B", False),
        ("y1", "2025-10-01 10:00", "LCK", "A", "B", True),
        ("y2", "2025-10-01 11:00", "LCK", "A", "B", True),
    ]
    assert rofs_q(_rofs_games(extra), CUT, LEAGUES, 4) == base
    flipped = [(*r[:5], not r[5]) if r[0] in ("z1", "z2", "z3") else r for r in extra]
    assert rofs_q(_rofs_games(flipped), CUT, LEAGUES, 4) == base


def test_rofs_q_without_continuations_raises():
    with pytest.raises(ValueError):
        rofs_q(_rofs_games(BASE_ROWS[:1]), CUT, LEAGUES, 4)


def test_rofs_q_missing_red_row_raises():
    games = _rofs_games(BASE_ROWS)
    games = games[~((games["gameid"] == "a2") & (games["side"] == "Red"))]
    with pytest.raises(ValueError):
        rofs_q(games, CUT, LEAGUES, 4)
