import dataclasses
import datetime
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from worlds.backtest import (
    BacktestResult,
    backtest_worlds,
    bootstrap_diff,
    brier,
    calibration_table,
    log_loss,
    matchup_class,
)
from worlds.elo import expected_score, replay

CUTOFF = pd.Timestamp("2025-10-14")
CONFIG = {
    "k_factor": 32,
    "initial_rating": 1500,
    "decay_half_life_days": 182,
    "decay_method": "none",
    "rating_updates": "in_tournament",
    "tournaments": {2025: {"start_date": datetime.date(2025, 10, 14)}},
}


def make_games(rows) -> pd.DataFrame:
    """rows: (gameid, date, league, blue, red, blue_won) -> two team rows per game."""
    out = []
    for gameid, date, league, blue, red, blue_won in rows:
        for side, team, won in (("Blue", blue, blue_won), ("Red", red, not blue_won)):
            out.append(
                {
                    "gameid": gameid,
                    "date": pd.Timestamp(date),
                    "league": league,
                    "teamname": team,
                    "side": side,
                    "result": int(won),
                }
            )
    return pd.DataFrame(out)


def fixture(g1_blue_won=True, g2_blue_won=True, mode="in_tournament"):
    """A beats B before the cutoff (A 1516, B 1484), then two WLDs games."""
    games = make_games(
        [
            ("g0", "2025-10-01 12:00", "LEC", "A", "B", True),
            ("g1", "2025-10-14 12:00", "WLDs", "A", "B", g1_blue_won),
            ("g2", "2025-10-15 12:00", "WLDs", "B", "A", g2_blue_won),
        ]
    )
    return games, {**CONFIG, "rating_updates": mode}


def run(games, config):
    return backtest_worlds(2025, games, config, CUTOFF)


def p_blue(result) -> list[float]:
    return result.predictions.sort_values("date")["p_blue"].tolist()


def test_backtest_result_fields():
    names = {f.name for f in dataclasses.fields(BacktestResult)}
    assert names == {
        "log_loss",
        "brier",
        "n_games",
        "calibration",
        "odds_log_loss",
        "predictions",
        "n_prestart_wlds",
        "history",
    }


def test_hand_computed_predictions_in_tournament():
    games, cfg = fixture()
    # g1: A 1516 vs B 1484 -> 1 / (1 + 10^(-32/400)) = 0.5460
    p1 = 1 / (1 + 10 ** (-32 / 400))
    assert p1 == pytest.approx(0.5460, abs=1e-4)
    # A wins g1: A = 1516 + 32 * (1 - p1) = 1530.53, B = 1469.47.
    # g2 (B blue): 1 / (1 + 10^(61.06/400)) = 0.4129
    p2 = 1 / (1 + 10 ** ((1516 + 32 * (1 - p1) - (1484 - 32 * (1 - p1))) / 400))
    assert p2 == pytest.approx(0.4129, abs=1e-3)
    res = run(games, cfg)
    assert p_blue(res) == pytest.approx([p1, p2])
    assert res.n_games == 2
    assert res.predictions["result"].tolist() == [1, 1]
    expected = -(math.log(p1) + math.log(p2)) / 2
    assert res.log_loss == pytest.approx(expected)
    assert res.odds_log_loss is None


def test_frozen_uses_pre_tournament_ratings_only():
    games, cfg = fixture(mode="frozen")
    p1 = 1 / (1 + 10 ** (-32 / 400))
    assert p_blue(run(games, cfg)) == pytest.approx([p1, 1 - p1])


@pytest.mark.parametrize("mode", ["in_tournament", "frozen"])
def test_changing_result_i_changes_no_prediction_up_to_i(mode):
    base, cfg = fixture(mode=mode)
    flipped, _ = fixture(g1_blue_won=False, mode=mode)
    a, b = p_blue(run(base, cfg)), p_blue(run(flipped, cfg))
    assert a[0] == b[0]  # game 1 itself and everything before it
    if mode == "in_tournament":
        assert a[1] != b[1]  # later game does see the new result
    else:
        assert a[1] == b[1]


def test_frozen_ignores_in_tournament_results_but_in_tournament_does_not():
    f_a, cfg_f = fixture(g1_blue_won=True, mode="frozen")
    f_b, _ = fixture(g1_blue_won=False, mode="frozen")
    assert p_blue(run(f_a, cfg_f)) == p_blue(run(f_b, cfg_f))
    i_a, cfg_i = fixture(g1_blue_won=True)
    i_b, _ = fixture(g1_blue_won=False)
    assert p_blue(run(i_a, cfg_i)) != p_blue(run(i_b, cfg_i))


def test_same_timestamp_games_do_not_see_each_other():
    def build(c_won):
        return make_games(
            [
                ("g0", "2025-10-01 12:00", "LEC", "A", "B", True),
                ("g1", "2025-10-14 12:00", "WLDs", "A", "C", True),
                ("g2", "2025-10-14 12:00", "WLDs", "A", "D", c_won),
            ]
        )

    cfg = {**CONFIG}
    a = run(build(True), cfg).predictions.set_index("gameid")["p_blue"]
    b = run(build(False), cfg).predictions.set_index("gameid")["p_blue"]
    # g1 and g2 share a timestamp and team A: g2 is predicted from pre-g1 ratings.
    assert a["g2"] == pytest.approx(1 / (1 + 10 ** (-16 / 400)))
    assert (a == b).all()  # g2's result can't move any prediction at that timestamp


def test_only_worlds_games_from_start_date_are_scored_but_all_update_ratings():
    games = make_games(
        [
            ("g0", "2025-10-01 12:00", "LEC", "A", "B", True),
            ("q", "2025-10-05 12:00", "WLDs", "A", "B", True),  # qualifier, pre-start
            ("x", "2025-10-14 10:00", "MSI", "B", "A", True),  # non-WLDs after cutoff
            ("g1", "2025-10-14 12:00", "WLDs", "A", "B", True),
        ]
    )
    res = run(games, CONFIG)
    assert res.predictions["gameid"].tolist() == ["g1"]
    # Ratings before g1: g0 and q (A beat B twice), then x (B beat A) at full K.
    ra, rb = 1500.0, 1500.0
    for a_won in (True, True, False):
        ea = 1 / (1 + 10 ** ((rb - ra) / 400))
        d = 32 * ((1.0 if a_won else 0.0) - ea)
        ra, rb = ra + d, rb - d
    assert p_blue(res)[0] == pytest.approx(1 / (1 + 10 ** ((rb - ra) / 400)))


def test_unseen_team_starts_at_initial_rating():
    games = make_games([("g1", "2025-10-14 12:00", "WLDs", "A", "B", True)])
    with pytest.warns(UserWarning):
        assert p_blue(run(games, CONFIG)) == [0.5]


def test_cutoff_after_start_date_raises():
    games, cfg = fixture()
    with pytest.raises(ValueError, match="cutoff"):
        backtest_worlds(2025, games, cfg, pd.Timestamp("2025-10-15"))


def test_unknown_rating_updates_raises():
    games, cfg = fixture()
    with pytest.raises(ValueError, match="rating_updates"):
        run(games, {**cfg, "rating_updates": "rolling"})


def test_constant_half_scores():
    p, y = np.full(4, 0.5), np.array([1, 0, 1, 1])
    assert log_loss(p, y) == pytest.approx(math.log(2))
    assert brier(p, y) == pytest.approx(0.25)


def test_log_loss_clips_extreme_probabilities():
    assert math.isfinite(log_loss(np.array([0.0, 1.0]), np.array([1, 0])))


def test_calibration_bins_from_favourite_view():
    p = np.array([0.55, 0.45, 0.95, 1.0, 0.7])
    y = np.array([1, 1, 1, 0, 0])
    table = calibration_table(p, y)
    assert len(table) == 5
    assert table["n"].sum() == len(p)
    assert table["n"].tolist() == [2, 0, 1, 0, 2]
    # 0.55 fav won; 0.45 -> fav is red (0.55), blue won so fav lost -> 0.5 observed
    assert table.loc[0, "observed"] == pytest.approx(0.5)
    assert table.loc[0, "mean_pred"] == pytest.approx(0.55)
    assert table.loc[4, "n"] == 2  # 1.0 lands in the last bin


def test_calibration_sums_to_n_games_for_a_backtest():
    games, cfg = fixture()
    res = run(games, cfg)
    assert res.calibration["n"].sum() == res.n_games


def test_unseen_scored_team_warns():
    games = make_games([("g1", "2025-10-14 12:00", "WLDs", "A", "B", True)])
    with pytest.warns(UserWarning, match="no games before"):
        run(games, CONFIG)


def test_bad_side_values_raise():
    games, cfg = fixture()
    games.loc[games["gameid"] == "g1", "side"] = ["Blue", "blue"]
    with pytest.raises(ValueError, match="Blue and one Red"):
        run(games, cfg)


def test_wlds_game_in_another_year_is_not_scored():
    games = make_games(
        [
            ("g0", "2025-10-01 12:00", "LEC", "A", "B", True),
            ("g1", "2025-10-14 12:00", "WLDs", "A", "B", True),
            ("g2", "2026-01-05 12:00", "WLDs", "A", "B", True),
        ]
    )
    assert run(games, CONFIG).predictions["gameid"].tolist() == ["g1"]


def test_prestart_wlds_games_are_counted_for_the_year_only():
    games = make_games(
        [
            ("g0", "2025-10-01 12:00", "LEC", "A", "B", True),
            ("q1", "2025-10-05 12:00", "WLDs", "A", "B", True),
            ("q2", "2025-10-06 12:00", "WLDs", "A", "B", True),
            ("old", "2024-10-06 12:00", "WLDs", "A", "B", True),  # other year
            ("x", "2025-10-07 12:00", "MSI", "A", "B", True),  # not WLDs
            ("g1", "2025-10-14 12:00", "WLDs", "A", "B", True),
        ]
    )
    res = run(games, CONFIG)
    assert res.n_prestart_wlds == 2
    assert res.predictions["gameid"].tolist() == ["g1"]


def test_prestart_count_changes_no_prediction():
    with_q = make_games(
        [
            ("g0", "2025-10-01 12:00", "LEC", "A", "B", True),
            ("q", "2025-10-05 12:00", "WLDs", "A", "B", True),
            ("g1", "2025-10-14 12:00", "WLDs", "A", "B", True),
        ]
    )
    as_lec = with_q.assign(league=with_q["league"].replace("WLDs", "LEC"))
    as_lec.loc[as_lec["gameid"] == "g1", "league"] = "WLDs"
    a, b = run(with_q, CONFIG), run(as_lec, CONFIG)
    assert (a.n_prestart_wlds, b.n_prestart_wlds) == (1, 0)
    assert p_blue(a) == p_blue(b)


def test_game_at_cutoff_instant_is_predicted_not_in_starting_ratings():
    games = make_games(
        [
            ("g0", "2025-10-01 12:00", "LEC", "A", "B", True),
            ("g1", "2025-10-14 00:00", "WLDs", "A", "B", True),
        ]
    )
    p = p_blue(run(games, CONFIG))
    assert p == pytest.approx([1 / (1 + 10 ** (-32 / 400))])


# ---- side advantage and league offsets in the backtest ----


def _h_fixture():
    """A prior year with 3 blue wins in 4 (H > 0), then g0 and two WLDs games."""
    rows = [
        (f"p{i}", f"2025-06-0{i + 1} 12:00", "LEC", "X", "Y", i < 3) for i in range(4)
    ]
    games, cfg = fixture()
    return pd.concat([make_games(rows), games], ignore_index=True), cfg


def test_defaults_without_new_keys_equal_explicit_off():
    games, cfg = fixture()
    explicit = {**cfg, "side_advantage": "none", "league_offsets": "off"}
    assert p_blue(run(games, cfg)) == p_blue(run(games, explicit))


def test_side_advantage_enters_prediction_and_update():
    games, cfg = _h_fixture()
    cfg = {**cfg, "side_advantage": "pre_cutoff_rate"}
    h = 400 * math.log10(4)  # prior window: p0-p3 plus g0, 4 blue wins of 5
    state = replay(games, CUTOFF, cfg)
    assert state.h == pytest.approx(h)
    res = run(games, cfg)
    first = res.predictions.sort_values("date")["p_blue"].iloc[0]
    assert first == pytest.approx(expected_score(state.team["A"], state.team["B"], h))
    # the update credits the win less than a no-H update would
    plain = replay(games, CUTOFF, {**cfg, "side_advantage": "none"})
    assert state.team["A"] < plain.team["A"]


def test_predictions_carry_league_keys_and_ignore_the_current_game():
    games, cfg = fixture()
    cfg = {
        **cfg,
        "league_offsets": "on",
        "k_league": 16,
        "international_leagues": ["WLDs"],
    }
    res = run(games, cfg)
    assert {"blue_league", "red_league"} <= set(res.predictions.columns)
    # g0 (LEC, A v B) is before the cutoff: both teams are LEC members
    assert set(res.predictions["blue_league"]) == {"LEC"}


def test_matchup_class():
    major = ["LCK", "LPL", "LEC", "LCS"]
    assert matchup_class("LCK", "LCK", major) == "same-league"
    assert matchup_class("LCK", "LPL", major) == "major-major"
    assert matchup_class("LPL", "PCS", major) == "major-minor"
    assert matchup_class("PCS", "PCS", major) == "same-league"
    assert matchup_class("PCS", "VCS", major) == "minor-minor"
    assert matchup_class(None, "LCK", major) == "unknown"


def test_bootstrap_diff_reproducible_and_brackets_the_mean():
    a = np.array([0.9, 0.5, 0.7, 0.4, 0.8, 0.6])
    b = a + 0.1
    r1 = bootstrap_diff(b, a, 500, np.random.default_rng(1))
    r2 = bootstrap_diff(b, a, 500, np.random.default_rng(1))
    assert r1 == r2
    mean, lo, hi = r1
    assert mean == pytest.approx(0.1)
    assert lo == pytest.approx(0.1) and hi == pytest.approx(0.1)
    c = np.array([0.0, 1.0, 0.0, 1.0])
    m, lo, hi = bootstrap_diff(c, np.zeros(4), 500, np.random.default_rng(2))
    assert lo < m < hi


# ---- per-game rating history (record=True) ----


def test_history_off_by_default():
    games, cfg = fixture()
    assert run(games, cfg).history is None


@pytest.mark.parametrize("mode", ["in_tournament", "frozen"])
def test_record_changes_no_output(mode):
    games, cfg = fixture(mode=mode)
    a = backtest_worlds(2025, games, cfg, CUTOFF)
    b = backtest_worlds(2025, games, cfg, CUTOFF, record=True)
    pd.testing.assert_frame_equal(a.predictions, b.predictions)
    pd.testing.assert_frame_equal(a.calibration, b.calibration)
    assert (a.log_loss, a.brier, a.n_games) == (b.log_loss, b.brier, b.n_games)


def test_history_before_equals_the_rating_that_predicted_each_game():
    games, cfg = fixture()
    res = backtest_worlds(2025, games, cfg, CUTOFF, record=True)
    h = res.history.set_index(["gameid", "team"])
    for g in res.predictions.itertuples(index=False):
        sb = h.loc[(g.gameid, g.blue), "rating_before"]
        sr = h.loc[(g.gameid, g.red), "rating_before"]
        assert expected_score(sb, sr, 0.0) == g.p_blue


def test_history_zero_sum_per_game_in_a_backtest():
    games, cfg = fixture()
    h = backtest_worlds(2025, games, cfg, CUTOFF, record=True).history
    d = (h["rating_after"] - h["rating_before"]).groupby(h["gameid"]).sum()
    assert d.abs().max() < 1e-9


def test_frozen_history_has_before_equal_after_in_tournament():
    games, cfg = fixture(mode="frozen")
    h = backtest_worlds(2025, games, cfg, CUTOFF, record=True).history
    wlds = h[h["gameid"].isin(["g1", "g2"])]
    assert len(wlds) == 4
    assert (wlds["rating_before"] == wlds["rating_after"]).all()


def test_history_in_tournament_after_feeds_the_next_games_before():
    games, cfg = fixture()
    h = backtest_worlds(2025, games, cfg, CUTOFF, record=True).history
    a1 = h[(h["gameid"] == "g1") & (h["team"] == "A")].iloc[0]
    a2 = h[(h["gameid"] == "g2") & (h["team"] == "A")].iloc[0]
    assert a2["rating_before"] == a1["rating_after"]


ROOT = Path(__file__).resolve().parents[1]
REAL = Path(__file__).resolve().parents[1] / "data/processed/games.parquet"


@pytest.mark.skipif(not REAL.exists(), reason="data/processed/games.parquet missing")
def test_real_data_pooled_log_loss_is_0_6614_with_and_without_record():
    games = pd.read_parquet(REAL)
    config = {
        **yaml.safe_load((ROOT / "config/elo.yaml").read_text()),
        **yaml.safe_load((ROOT / "config/backtest.yaml").read_text()),
        "international_leagues": yaml.safe_load(
            (ROOT / "config/ingest.yaml").read_text()
        )["international_leagues"],
    }
    out = []
    for record in (False, True):
        preds = pd.concat(
            backtest_worlds(
                y, games, config, pd.Timestamp(t["start_date"]), record=record
            ).predictions
            for y, t in config["tournaments"].items()
        )
        out.append(log_loss(preds["p_blue"], preds["result"]))
    assert round(out[0], 4) == 0.6614
    assert out[0] == out[1]


def test_history_scored_flag_marks_only_predicted_games():
    games, cfg = fixture()
    res = backtest_worlds(2025, games, cfg, CUTOFF, record=True)
    h = res.history
    assert set(h.loc[h["scored"], "gameid"]) == {"g1", "g2"}
    assert set(h.loc[~h["scored"], "gameid"]) == {"g0"}


@pytest.mark.parametrize("h_on", [False, True])
def test_history_before_equals_predicting_strength_with_h_and_offsets(h_on):
    games = make_games(
        [
            ("g0", "2025-10-01 12:00", "LCK", "A", "B", True),
            ("g1", "2025-10-02 12:00", "LPL", "C", "D", False),
            ("m1", "2025-10-05 12:00", "MSI", "A", "C", True),
            ("g2", "2025-10-14 12:00", "WLDs", "A", "D", True),
            ("g3", "2025-10-15 12:00", "WLDs", "C", "B", False),
        ]
    )
    cfg = {
        **CONFIG,
        "league_offsets": "on",
        "k_league": 16,
        "international_leagues": ["WLDs", "MSI"],
        "side_advantage": "pre_cutoff_rate" if h_on else "none",
        "side_advantage_window_days": 365,
    }
    res = backtest_worlds(2025, games, cfg, CUTOFF, record=True)
    h = res.history.set_index(["gameid", "team"])
    hh = elo_h(games, cfg) if h_on else 0.0
    for g in res.predictions.itertuples(index=False):
        sb = h.loc[(g.gameid, g.blue)]
        sr = h.loc[(g.gameid, g.red)]
        p = expected_score(
            sb["rating_before"] + sb["offset_before"],
            sr["rating_before"] + sr["offset_before"],
            hh,
        )
        assert p == g.p_blue


def elo_h(games, cfg):
    return replay(games, CUTOFF, cfg).h
