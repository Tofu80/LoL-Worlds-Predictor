import pandas as pd
import pytest

from worlds.elo import compute_ratings, decay_weight, expected_score, update_ratings


def test_expected_score_equal_ratings():
    assert expected_score(1500, 1500) == pytest.approx(0.5)


def test_expected_score_higher_rated_wins_more():
    assert expected_score(1600, 1500) > 0.5
    assert expected_score(1500, 1600) < 0.5


def test_expected_score_symmetry():
    assert expected_score(1600, 1500) == pytest.approx(1 - expected_score(1500, 1600))


def test_update_zero_sum():
    ra, rb = update_ratings(1500, 1500, result=1.0, k=32)
    delta_a = ra - 1500
    delta_b = rb - 1500
    assert delta_a == pytest.approx(-delta_b)


def test_update_fifty_fifty_moves_by_k_over_2():
    ra, rb = update_ratings(1500, 1500, result=1.0, k=32)
    assert ra - 1500 == pytest.approx(16.0)
    assert 1500 - rb == pytest.approx(16.0)


def test_update_winner_gains_loser_loses():
    ra, rb = update_ratings(1500, 1500, result=1.0, k=32)
    assert ra > 1500
    assert rb < 1500


def test_update_upset_gains_more():
    ra_upset, _ = update_ratings(1300, 1700, result=1.0, k=32)
    ra_expected, _ = update_ratings(1700, 1300, result=1.0, k=32)
    assert ra_upset - 1300 > ra_expected - 1700


K, INIT, HL = 32, 1500, 182
CUTOFF = pd.Timestamp("2024-07-01")


def _games(rows):
    """rows: (gameid, date, blue, red, blue_won) -> two team rows per game."""
    out = []
    for gid, date, blue, red, blue_won in rows:
        d = pd.Timestamp(date)
        out.append(
            {
                "gameid": gid,
                "date": d,
                "teamname": blue,
                "side": "Blue",
                "result": int(blue_won),
            }
        )
        out.append(
            {
                "gameid": gid,
                "date": d,
                "teamname": red,
                "side": "Red",
                "result": int(not blue_won),
            }
        )
    return pd.DataFrame(out)


SAMPLE = _games(
    [
        ("g1", "2024-01-10", "A", "B", True),
        ("g2", "2024-01-10", "C", "D", False),  # same day as g1: tie broken by gameid
        ("g3", "2024-03-05", "A", "C", True),
        ("g4", "2024-05-20", "B", "D", True),
        ("g5", "2024-06-30", "D", "A", True),
    ]
)


def _run(games, method="k_scale"):
    return compute_ratings(games, CUTOFF, K, INIT, HL, method)


def test_decay_weight_halves_each_half_life():
    assert decay_weight(0, HL) == pytest.approx(1.0)
    assert decay_weight(HL, HL) == pytest.approx(0.5)
    assert decay_weight(2 * HL, HL) == pytest.approx(0.25)


def test_fifty_fifty_game_at_half_life_moves_k_over_4():
    date = CUTOFF - pd.Timedelta(days=HL)
    r = _run(_games([("g1", date, "A", "B", True)]))
    assert r["A"] - INIT == pytest.approx(K / 4)
    assert INIT - r["B"] == pytest.approx(K / 4)


def test_games_on_or_after_cutoff_are_ignored():
    extra = _games(
        [
            ("g6", CUTOFF, "A", "B", False),
            ("g7", CUTOFF + pd.Timedelta(days=3), "E", "A", True),  # E must not appear
        ]
    )
    assert _run(pd.concat([SAMPLE, extra])) == _run(SAMPLE)


def test_decay_none_matches_plain_elo_replay():
    ratings = {t: float(INIT) for t in "ABCD"}
    for w, l in [("A", "B"), ("D", "C"), ("A", "C"), ("B", "D"), ("D", "A")]:
        ratings[w], ratings[l] = update_ratings(ratings[w], ratings[l], 1.0, K)
    assert _run(SAMPLE, "none") == pytest.approx(ratings)


@pytest.mark.parametrize("method", ["k_scale", "none"])
def test_compute_ratings_zero_sum(method):
    r = _run(SAMPLE, method)
    assert sum(r.values()) == pytest.approx(len(r) * INIT)


def test_row_order_does_not_matter():
    shuffled = SAMPLE.sample(frac=1, random_state=0).reset_index(drop=True)
    assert _run(shuffled) == pytest.approx(_run(SAMPLE))


def test_all_teams_seen_are_returned():
    assert set(_run(SAMPLE)) == {"A", "B", "C", "D"}


@pytest.mark.parametrize(
    "bad",
    [
        lambda g: g.iloc[1:],  # gameid with 1 row
        lambda g: pd.concat([g, g.iloc[[0]]]),  # gameid with 3 rows
        lambda g: g.assign(result=[1, 1] + list(g["result"][2:])),  # two winners
        lambda g: g.assign(result=[0.5, 0.5] + list(g["result"][2:])),  # sums to 1
    ],
    ids=["one_row", "three_rows", "two_winners", "half_results"],
)
def test_malformed_game_raises(bad):
    with pytest.raises(ValueError):
        _run(bad(SAMPLE))


def test_unknown_decay_method_raises():
    with pytest.raises(ValueError):
        _run(SAMPLE, "regress_to_mean")
