import copy
import functools
import random

import numpy as np
import pandas as pd
import pytest

from worlds.simulate import (
    load_config,
    predict,
    run_simulation,
    validate_pre_cutoff,
)

CFG = load_config()
TEAMS = CFG["teams"]
LEAGUE_OF = {
    t: lg
    for lg, chunk in zip(["LCK", "LPL", "LEC", "LCS"], [TEAMS[i::4] for i in range(4)])
    for t in chunk
}
CUTOFF = pd.Timestamp(CFG["prediction_cutoff"])
EXTRA_PLAYIN = "Cloud9"  # a play-in team that is not one of the 16


def _rows_to_games(rows):
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


@functools.lru_cache(maxsize=1)
def _swiss_pairs():
    """(winner, loser) pairs giving every team its final Swiss record."""
    res = {t: tuple(r) for t, r in CFG["swiss_results"].items()}
    out_wins = [2, 2, 1, 1, 1, 1, 1, 0]  # eliminated teams: x-3, wins sum to 9
    for t, w in zip([t for t in TEAMS if t not in res], out_wins):
        res[t] = (w, 3)
    wins = [t for t, (w, _) in sorted(res.items()) for _ in range(w)]
    losses = [t for t, (_, l) in sorted(res.items()) for _ in range(l)]
    assert len(wins) == len(losses)
    rnd = random.Random(0)
    while True:
        rnd.shuffle(losses)
        pairs = [frozenset(x) for x in zip(wins, losses)]
        if all(w != l for w, l in zip(wins, losses)) and len(set(pairs)) == len(pairs):
            return list(zip(wins, losses))


def build_games(extra=(), swiss_flip=None):
    rows = []
    # history: domestic games and a Bo3 (continuations for q), all before the play-in
    teams_by_league = {}
    for t, lg in LEAGUE_OF.items():
        teams_by_league.setdefault(lg, []).append(t)
    n = 0
    for lg, ts in teams_by_league.items():
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                n += 1
                for k in range(3):  # a Bo3-like run an hour apart
                    rows.append(
                        (
                            f"h{n}_{k}",
                            pd.Timestamp("2026-08-01") + pd.Timedelta(days=n, hours=k),
                            lg,
                            ts[i] if (n + k) % 2 else ts[j],
                            ts[j] if (n + k) % 2 else ts[i],
                            (n + k) % 3 != 0,
                        )
                    )
    # play-in: Karmine Corp beats an outside team
    rows.append(("p1", "2026-10-15 18:00", "WLDs", "Karmine Corp", EXTRA_PLAYIN, True))
    # swiss: one Bo1 every 6h from 2026-10-23 12:00
    for i, (w, l) in enumerate(_swiss_pairs()):
        d = pd.Timestamp("2026-10-23 12:00") + pd.Timedelta(hours=6 * i)
        blue_win = i % 2 == 0
        rows.append(
            (f"s{i}", d, "WLDs", w if blue_win else l, l if blue_win else w, blue_win)
        )
    rows.extend(extra)
    return _rows_to_games(rows)


def knockout_rows(flip=False):
    return [
        ("k1", "2026-11-03 22:00", "WLDs", "Dplus Kia", "Bilibili Gaming", not flip),
        ("k2", "2026-11-04 22:00", "WLDs", "Gen.G", "LYON", not flip),
        ("k3", "2026-11-05 22:00", "WLDs", "LYON", "Gen.G", flip),
    ]


def test_fixture_validates():
    summary = validate_pre_cutoff(build_games(), CFG)
    assert summary["n_swiss_games"] == 33


def test_title_odds_sum_to_one():
    out = predict(build_games(), CFG, 400, np.random.default_rng(1))
    t = out["table"]
    assert t["title"].sum() == pytest.approx(1.0)
    assert t["final"].sum() == pytest.approx(2.0)
    assert t["semifinal"].sum() == pytest.approx(4.0)
    assert set(t.index) == set(CFG["swiss_results"])


def test_same_seed_same_output():
    a = predict(build_games(), CFG, 300, np.random.default_rng(7))["table"]
    b = predict(build_games(), CFG, 300, np.random.default_rng(7))["table"]
    pd.testing.assert_frame_equal(a, b)


def test_post_cutoff_results_change_nothing():
    base = predict(build_games(), CFG, 300, np.random.default_rng(7))
    for flip in (False, True):
        extra = knockout_rows(flip) + [
            ("lck1", "2026-11-10 09:00", "LCK", TEAMS[0], TEAMS[4], flip)
        ]
        got = predict(build_games(extra), CFG, 300, np.random.default_rng(7))
        pd.testing.assert_frame_equal(got["table"], base["table"])
        assert (got["h"], got["q"], got["n_q"]) == (base["h"], base["q"], base["n_q"])


def test_game_exactly_at_cutoff_is_not_used():
    base = predict(build_games(), CFG, 100, np.random.default_rng(7))
    extra = [("edge", CUTOFF, "LCK", TEAMS[0], TEAMS[4], True)]
    got = predict(build_games(extra), CFG, 100, np.random.default_rng(7))
    pd.testing.assert_frame_equal(got["table"], base["table"])


def test_wrong_swiss_record_raises():
    cfg = copy.deepcopy(CFG)
    cfg["swiss_results"]["T1"] = [3, 2]
    with pytest.raises(ValueError, match="T1"):
        validate_pre_cutoff(build_games(), cfg)


def test_non_swiss_wlds_game_raises():
    extra = [("odd", "2026-10-25 06:00", "WLDs", "Cloud9", "Fnatic", True)]
    with pytest.raises(ValueError, match="play-in or Swiss"):
        validate_pre_cutoff(build_games(extra), CFG)


def test_game_between_last_swiss_game_and_cutoff_raises():
    extra = [("gap", "2026-11-01 12:00", "LCK", TEAMS[0], TEAMS[4], True)]
    with pytest.raises(ValueError, match="last Swiss game"):
        validate_pre_cutoff(build_games(extra), CFG)


def test_pre_start_wlds_games_are_counted_as_qualifiers():
    extra = [("qual", "2026-09-17 09:00", "WLDs", "Cloud9", "Fnatic", True)]
    summary = validate_pre_cutoff(build_games(extra), CFG)
    assert summary["n_qualifier_wlds"] == 1


def test_run_simulation_sigma_zero_is_deterministic_in_strengths():
    strengths = {t: 1500.0 + 10 * i for i, t in enumerate(CFG["swiss_results"])}
    a = run_simulation(strengths, 23.0, 0.2, CFG, 200, np.random.default_rng(1), 0.0)
    b = run_simulation(strengths, 23.0, 0.2, CFG, 200, np.random.default_rng(1), 0.0)
    pd.testing.assert_frame_equal(a, b)
    assert a["title"].sum() == pytest.approx(1.0)


# ---- leakage-review follow-ups ----


def test_frozen_rating_updates_keep_ratings_at_start_date():
    from worlds import elo
    from worlds.simulate import rating_state

    games = build_games()
    frozen = rating_state(games, {**CFG, "rating_updates": "frozen"})
    live = rating_state(games, {**CFG, "rating_updates": "in_tournament"})
    start = pd.Timestamp(CFG["start_date"])
    assert frozen.team == elo.replay(games, start, CFG).team
    assert frozen.team != live.team


def test_unknown_rating_updates_raises():
    from worlds.simulate import rating_state

    with pytest.raises(ValueError, match="rating_updates"):
        rating_state(build_games(), {**CFG, "rating_updates": "bogus"})


def test_data_hash_covers_pre_cutoff_rows_only():
    from worlds.simulate import games_sha256

    base = games_sha256(build_games(), CFG)
    assert games_sha256(build_games(knockout_rows(False)), CFG) == base
    assert games_sha256(build_games(knockout_rows(True)), CFG) == base
    flipped = build_games()
    flipped.loc[flipped["gameid"] == "s0", "result"] = (
        1 - flipped.loc[flipped["gameid"] == "s0", "result"]
    )
    assert games_sha256(flipped, CFG) != base


def test_no_wlds_games_raises_clear_error():
    games = build_games()
    games = games[games["league"] != "WLDs"]
    with pytest.raises(ValueError, match="no Swiss games"):
        validate_pre_cutoff(games, CFG)


def test_non_swiss_game_at_last_swiss_timestamp_raises():
    last = build_games()
    last_date = last[last["gameid"].str.startswith("s")]["date"].max()
    extra = [("tie", last_date, "LCK", TEAMS[0], TEAMS[4], True)]
    with pytest.raises(ValueError, match="last Swiss game"):
        validate_pre_cutoff(build_games(extra), CFG)


def test_swiss_rematch_raises():
    pairs = _swiss_pairs()
    w, l = pairs[0]
    extra = [("rem", "2026-10-31 20:00", "WLDs", w, l, True)]
    with pytest.raises(ValueError, match="twice"):
        validate_pre_cutoff(build_games(extra), CFG)


def test_team_count_must_match_swiss_total():
    cfg = {**CFG, "teams": CFG["teams"][:-1]}
    with pytest.raises(ValueError, match="total_teams"):
        validate_pre_cutoff(build_games(), cfg)


def test_write_outputs_refuses_to_overwrite(tmp_path, monkeypatch):
    from worlds import simulate

    raw = tmp_path / "raw.csv"
    raw.write_text("x")
    monkeypatch.setattr(simulate, "RAW_2026", raw)
    monkeypatch.setattr(simulate, "OUT_DIRS", [tmp_path / "out"])
    games = build_games()
    result = predict(games, CFG, 50, np.random.default_rng(1))
    paths = simulate.write_outputs(result, CFG, games, 42)
    assert all(p.exists() for p in paths)
    meta = __import__("json").loads(paths[0].read_text())["meta"]
    assert "data_sha256" in meta and meta["csv_snapshot"]["covers_post_cutoff_rows"]
    with pytest.raises(FileExistsError):
        simulate.write_outputs(result, CFG, games, 42)


def test_predict_reports_games_per_q_league():
    out = predict(build_games(), CFG, 20, np.random.default_rng(1))
    assert out["q_league_games"]["LCK"] > 0
    assert out["q_league_games"]["CBLOL"] == 0
