import math

import pandas as pd
import pytest

from worlds.elo import (
    EloState,
    blue_advantage,
    compute_ratings,
    decay_weight,
    expected_score,
    replay,
    update_ratings,
)


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


# ---- side advantage (H) and league offsets ----

INTL = ["WLDs", "MSI"]
BASE = {
    "k_factor": 32,
    "initial_rating": 1500,
    "decay_half_life_days": 182,
    "decay_method": "none",
    "international_leagues": INTL,
    "league_lineage": {"LTA N": "LCS", "LTA S": "CBLOL"},
    "league_membership_skip": ["LTA"],
    "league_inherit": {"LCP": {"PCS": 3, "LJL": 3, "VCS": 4}},
}
ON = {**BASE, "league_offsets": "on", "k_league": 16}


def _lg(rows):
    """rows: (gameid, date, league, blue, red, blue_won)."""
    df = _games([(g, d, b, r, w) for g, d, _, b, r, w in rows])
    leagues = {g: lg for g, _, lg, _, _, _ in rows}
    df["league"] = df["gameid"].map(leagues)
    return df


def test_h_zero_and_offsets_off_reproduce_compute_ratings():
    games = _lg(
        [
            (g, d, "LCK", b, r, w)
            for g, d, b, r, w in [
                ("g1", "2024-01-10", "A", "B", True),
                ("g2", "2024-03-05", "B", "C", False),
                ("g3", "2024-05-20", "C", "A", True),
            ]
        ]
    )
    cfg = {
        **BASE,
        "decay_method": "k_scale",
        "side_advantage": "none",
        "league_offsets": "off",
    }
    state = replay(games, CUTOFF, cfg)
    assert state.team == compute_ratings(games, CUTOFF, K, INIT, HL, "k_scale")
    assert state.h == 0.0
    assert state.league == {}


def test_blue_advantage_hand_computed():
    # window [2023-12-31, 2024-01-10 ... ): 3 blue wins of 4 -> r = 0.75
    rows = [
        ("g1", "2024-01-01", "LCK", "A", "B", True),
        ("g2", "2024-01-02", "LCK", "A", "B", True),
        ("g3", "2024-01-03", "LCK", "A", "B", True),
        ("g4", "2024-01-04", "LCK", "A", "B", False),
    ]
    h = blue_advantage(_lg(rows), pd.Timestamp("2024-02-01"), 365)
    assert h == pytest.approx(400 * math.log10(3))


def test_blue_advantage_uses_only_window_before_cutoff():
    rows = [
        ("g1", "2022-01-01", "LCK", "A", "B", True),  # before the window
        ("g2", "2024-01-02", "LCK", "A", "B", True),
        ("g3", "2024-01-03", "LCK", "A", "B", False),
        ("g4", "2024-02-01", "LCK", "A", "B", True),  # at the cutoff
        ("g5", "2024-03-01", "LCK", "A", "B", True),
    ]  # after the cutoff
    cutoff = pd.Timestamp("2024-02-01")
    assert blue_advantage(_lg(rows), cutoff, 365) == pytest.approx(0.0)
    flipped = _lg(
        [
            (g, d, lg, b, r, not w if g in ("g1", "g4", "g5") else w)
            for g, d, lg, b, r, w in rows
        ]
    )
    assert blue_advantage(flipped, cutoff, 365) == pytest.approx(0.0)


def test_side_advantage_option_validated():
    games = _lg([("g1", "2024-01-01", "LCK", "A", "B", True)])
    with pytest.raises(ValueError):
        replay(games, CUTOFF, {**BASE, "side_advantage": "bogus"})
    with pytest.raises(ValueError):
        replay(games, CUTOFF, {**BASE, "league_offsets": "maybe"})


def test_blue_bonus_in_expected_score_and_updates_zero_sum():
    assert expected_score(1500, 1500, 23.0) > 0.5
    ea = expected_score(1500, 1500, 400 * math.log10(1.5))
    assert ea == pytest.approx(0.6)
    na, nb = update_ratings(1500, 1500, 1.0, 32, h=100.0)
    assert (na - 1500) + (nb - 1500) == pytest.approx(0.0)


def test_blue_win_credited_less_than_red_win_with_h():
    cfg = {**BASE, "side_advantage": "pre_cutoff_rate", "league_offsets": "off"}
    # prior window: 3 blue wins of 4 so H > 0
    prior = [
        ("p1", "2024-01-01", "LCK", "X", "Y", True),
        ("p2", "2024-01-02", "LCK", "X", "Y", True),
        ("p3", "2024-01-03", "LCK", "X", "Y", True),
        ("p4", "2024-01-04", "LCK", "X", "Y", False),
    ]
    blue_win = replay(
        _lg(prior + [("g", "2024-02-01", "LCK", "A", "B", True)]), CUTOFF, cfg
    ).team
    red_win = replay(
        _lg(prior + [("g", "2024-02-01", "LCK", "A", "B", False)]), CUTOFF, cfg
    ).team
    assert blue_win["A"] - 1500 < red_win["B"] - 1500  # A gains less than B would
    assert blue_win["A"] + blue_win["B"] == pytest.approx(3000)
    assert red_win["A"] + red_win["B"] == pytest.approx(3000)


def test_domestic_game_does_not_move_league_ratings():
    games = _lg(
        [
            ("g1", "2024-01-10", "LCK", "A", "B", True),
            ("g2", "2024-01-11", "LPL", "C", "D", False),
        ]
    )
    state = replay(games, CUTOFF, ON)
    assert all(v == 0.0 for v in state.league.values())
    assert state.member == {"A": "LCK", "B": "LCK", "C": "LPL", "D": "LPL"}


def _home(*rows):
    return [
        ("h1", "2024-01-01", "LCK", "A", "A2", True),
        ("h2", "2024-01-01 01:00", "LPL", "B", "B2", True),
    ] + list(rows)


def test_fifty_fifty_international_moves_each_league_by_half_k_league():
    state = EloState(
        initial=1500.0,
        k_league=16.0,
        international=frozenset(INTL),
        member={"A": "LCK", "B": "LPL"},
    )
    assert state.p_blue("A", "B") == pytest.approx(0.5)
    state.update("A", "B", "WLDs", True, k=32)
    assert state.league["LCK"] == pytest.approx(8.0)  # k_league / 2
    assert state.league["LPL"] == pytest.approx(-8.0)
    assert state.team["A"] - 1500 == pytest.approx(16.0)  # K / 2


def test_international_cross_league_moves_leagues_zero_sum():
    games = _lg(_home(("w", "2024-02-01", "MSI", "A", "B", True)))
    state = replay(games, CUTOFF, ON)
    assert state.league["LCK"] == pytest.approx(16 * 0.5)
    assert state.league["LPL"] == pytest.approx(-16 * 0.5)
    assert sum(state.league.values()) == pytest.approx(0.0)
    # team level: zero-sum over all teams
    assert sum(v - 1500 for v in state.team.values()) == pytest.approx(0.0)


def test_same_league_international_game_does_not_move_league_ratings():
    games = _lg(
        [
            ("h1", "2024-01-01", "LCK", "A", "B", True),
            ("w", "2024-02-01", "WLDs", "A", "B", True),
        ]
    )
    state = replay(games, CUTOFF, ON)
    assert state.league.get("LCK", 0.0) == 0.0


def test_international_game_does_not_set_membership():
    games = _lg(_home(("w", "2024-02-01", "MSI", "A", "B", True)))
    assert replay(games, CUTOFF, ON).member["A"] == "LCK"


def test_league_term_enters_strength_and_prediction():
    games = _lg(_home(("w", "2024-02-01", "MSI", "A", "B", True)))
    state = replay(games, CUTOFF, ON)
    assert state.strength("A") == pytest.approx(state.team["A"] + 8.0)
    assert state.p_blue("A", "B") == pytest.approx(
        expected_score(state.strength("A"), state.strength("B"), state.h)
    )


def test_membership_uses_only_games_before_t():
    base = _home(("w", "2024-02-01", "MSI", "A", "B", True))
    late = _lg(base + [("later", "2024-03-01", "LEC", "A", "Z", True)])
    state = replay(late, pd.Timestamp("2024-02-15"), ON)  # later is after cutoff
    assert state.member["A"] == "LCK"
    state2 = replay(late, pd.Timestamp("2024-04-01"), ON)
    assert state2.member["A"] == "LEC"


def test_post_cutoff_perturbation_changes_nothing():
    a = _lg(_home(("w", "2024-02-01", "MSI", "A", "B", True)))
    b = _lg(
        _home(
            ("w", "2024-02-01", "MSI", "A", "B", True),
            ("x", "2024-08-01", "LEC", "A", "Z", False),
        )
    )
    sa, sb = replay(a, CUTOFF, ON), replay(b, CUTOFF, ON)
    assert sa.team == sb.team and sa.league == sb.league
    assert sa.member == sb.member and sa.h == sb.h


def test_lineage_and_skip_and_inherit():
    games = _lg(
        [
            ("g1", "2024-01-01", "LTA N", "A", "B", True),
            ("g2", "2024-01-02", "LTA", "A", "C", True),
        ]
    )
    state = replay(games, CUTOFF, ON)
    assert state.member["A"] == "LCS" and state.member["B"] == "LCS"
    assert "C" not in state.member  # LTA label never sets membership
    # LCP starts at the weighted mean of its predecessors' ratings
    pre = _lg(
        [
            ("p1", "2024-01-01", "PCS", "P", "P2", True),
            ("p2", "2024-01-02", "LJL", "J", "J2", True),
            ("p3", "2024-01-03", "VCS", "V", "V2", True),
            ("i1", "2024-01-10", "WLDs", "P", "V", True),
            ("i2", "2024-01-11", "WLDs", "J", "V2", True),
            ("c1", "2024-02-01", "LCP", "Q", "Q2", True),
        ]
    )
    s = replay(pre, CUTOFF, ON)
    want = (3 * s.league["PCS"] + 3 * s.league["LJL"] + 4 * s.league["VCS"]) / 10
    assert s.league["LCP"] == pytest.approx(want)
    assert s.member["Q"] == "LCP"


def test_game_without_one_blue_and_one_red_row_raises():
    games = _games([("g1", "2024-01-10", "A", "B", True)])
    games.loc[games["teamname"] == "B", "side"] = "Blue"
    with pytest.raises(ValueError, match="Blue and one Red"):
        compute_ratings(games, CUTOFF, K, INIT, HL, "none")
