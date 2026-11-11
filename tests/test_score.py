import copy
import itertools
import math
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from worlds import score
from worlds.elo import expected_score
from worlds.series import bo5_rofs_win_prob
from worlds.simulate import load_config, run_simulation

CFG = yaml.safe_load(Path("config/worlds_2026.yaml").read_text())
QFS = CFG["knockout"]["quarterfinals"]
TEAMS = [t for pair in QFS for t in pair]
STRENGTHS = {t: 1500.0 + 35 * i for i, t in enumerate(TEAMS)}
H, Q, SIGMA, NODES = 23.0, 0.2, 50.0, 41


def tag_exists() -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "refs/tags/pred-2026-preQF"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


# ---------- series probability: brute force ----------


def brute_bo5(sa, sb, h, q, g1):
    """P(A wins a Bo5) summing over all 5-game (side, winner) sequences, written
    independently of series.py (no recursion, no cache)."""
    ea_blue, ea_red = expected_score(sa, sb, h), expected_score(sa, sb, -h)
    total = 0.0
    for seq in itertools.product(
        itertools.product((True, False), (True, False)), repeat=5
    ):
        prob, wa, wb, prev_loser = 1.0, 0, 0, None
        a_won_series = None
        for a_blue, a_wins in seq:
            q_a = g1 if prev_loser is None else (q if prev_loser == "A" else 1 - q)
            prob *= q_a if a_blue else 1 - q_a
            e = ea_blue if a_blue else ea_red
            prob *= e if a_wins else 1 - e
            if a_won_series is None:
                wa, wb = wa + a_wins, wb + (not a_wins)
                if wa == 3:
                    a_won_series = True
                elif wb == 3:
                    a_won_series = False
            prev_loser = "B" if a_wins else "A"
        total += prob if a_won_series else 0.0
    return total


@pytest.mark.parametrize(
    "a,b,round_name,g1",
    [
        ("Dplus Kia", "Bilibili Gaming", "quarterfinals", Q),  # 3-0 v 3-2: A holds
        ("Bilibili Gaming", "Dplus Kia", "quarterfinals", 1 - Q),
        ("Top Esports", "Invictus Gaming", "quarterfinals", 0.5),  # equal records
        ("T1", "Dplus Kia", "semifinals", 0.5),
        ("Gen.G", "T1", "final", 0.5),
    ],
)
def test_series_prob_zero_noise_matches_brute_force(a, b, round_name, g1):
    got = score.series_prob(a, b, round_name, STRENGTHS, H, Q, CFG, 0.0, NODES)
    assert got == pytest.approx(
        brute_bo5(STRENGTHS[a], STRENGTHS[b], H, Q, g1), abs=1e-12
    )


def test_series_prob_noise_matches_dense_integral():
    a, b = "Dplus Kia", "Bilibili Gaming"
    sd = SIGMA * math.sqrt(2)
    d = np.linspace(-8 * sd, 8 * sd, 40001)
    pdf = np.exp(-0.5 * (d / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
    f = np.array(
        [bo5_rofs_win_prob(STRENGTHS[a] + x, STRENGTHS[b], H, Q, Q) for x in d]
    )
    want = np.trapezoid(f * pdf, d)
    got = score.series_prob(a, b, "quarterfinals", STRENGTHS, H, Q, CFG, SIGMA, NODES)
    assert got == pytest.approx(want, abs=1e-7)


def test_series_prob_antisymmetric_when_game1_is_a_coin_flip():
    p = score.series_prob(
        "T1", "Gen.G", "semifinals", STRENGTHS, H, Q, CFG, SIGMA, NODES
    )
    r = score.series_prob(
        "Gen.G", "T1", "semifinals", STRENGTHS, H, Q, CFG, SIGMA, NODES
    )
    assert p + r == pytest.approx(1.0, abs=1e-12)


def test_game_prob_noise_free_is_elo_with_blue_bonus():
    got = score.game_prob("T1", "Gen.G", STRENGTHS, H, 0.0, NODES)
    assert got == pytest.approx(expected_score(STRENGTHS["T1"], STRENGTHS["Gen.G"], H))


def test_game_prob_noise_shrinks_towards_half():
    sure = score.game_prob("Gen.G", "LYON", STRENGTHS, H, 0.0, NODES)
    noisy = score.game_prob("Gen.G", "LYON", STRENGTHS, H, SIGMA, NODES)
    assert 0.5 < noisy < sure or sure < noisy < 0.5


# ---------- bracket odds ----------


def test_bracket_odds_all_fair():
    odds = score.bracket_odds(lambda r, a, b: 0.5, QFS, CFG["knockout"]["semifinals"])
    for t in TEAMS:
        assert odds[t] == pytest.approx(
            {"semifinal": 0.5, "final": 0.25, "title": 0.125}
        )


def test_bracket_odds_hand_computed():
    def pf(r, a, b):
        return 0.8 if (r, a) == ("quarterfinals", "Dplus Kia") else 0.5

    odds = score.bracket_odds(pf, QFS, CFG["knockout"]["semifinals"])
    assert odds["Dplus Kia"]["semifinal"] == pytest.approx(0.8)
    assert odds["Dplus Kia"]["title"] == pytest.approx(0.8 * 0.5 * 0.5)
    assert odds["Bilibili Gaming"]["title"] == pytest.approx(0.2 * 0.25)
    assert odds["Gen.G"]["title"] == pytest.approx(0.125)
    assert sum(o["title"] for o in odds.values()) == pytest.approx(1.0)


# ---------- round-level scoring ----------


def test_round_scores_hand_values():
    ps = [0.9] * 4 + [0.1] * 4
    odds = {t: {"semifinal": p, "final": 0.5, "title": 0.5} for t, p in zip(TEAMS, ps)}
    outcomes = {"semifinal": set(TEAMS[:4])}  # final and title not known yet
    got = score.round_scores(odds, outcomes)
    assert set(got) == {"semifinal"}
    assert got["semifinal"]["n"] == 8
    assert got["semifinal"]["log_loss"] == pytest.approx(-math.log(0.9))
    assert got["semifinal"]["brier"] == pytest.approx(0.01)


def test_round_scores_uniform_half():
    odds = {t: {"semifinal": 0.5, "final": 0.25, "title": 0.125} for t in TEAMS}
    outcomes = {"title": {TEAMS[0]}}
    got = score.round_scores(odds, outcomes)["title"]
    want = (-math.log(0.125) - 7 * math.log(0.875)) / 8
    assert got["log_loss"] == pytest.approx(want)
    assert got["brier"] == pytest.approx((0.875**2 + 7 * 0.125**2) / 8)


# ---------- margin removal and odds snapshots ----------


def test_margin_free_sums_to_one():
    p = score.margin_free({"A": 1.80, "B": 2.10})
    assert sum(p.values()) == pytest.approx(1.0)
    raw_a, raw_b = 1 / 1.80, 1 / 2.10
    assert p["A"] == pytest.approx(raw_a / (raw_a + raw_b))
    assert raw_a + raw_b > 1  # there was a margin to remove


def test_margin_free_rejects_odds_not_above_one():
    with pytest.raises(ValueError):
        score.margin_free({"A": 1.0, "B": 3.0})


def snapshot(path, series, ts, bookmaker, odds):
    path.write_text(
        yaml.safe_dump(
            {
                "series": series,
                "bookmaker": bookmaker,
                "timestamp_utc": ts,
                "odds": odds,
            }
        )
    )


def test_odds_pick_latest_before_start_and_reject_later(tmp_path):
    a, b = QFS[0]
    start = pd.Timestamp("2026-11-03T22:00:00")
    snapshot(
        tmp_path / "worlds_2026_QF1_a.yaml",
        "QF1",
        "2026-11-02T10:00:00",
        "X",
        {a: 1.5, b: 2.6},
    )
    snapshot(
        tmp_path / "worlds_2026_QF1_b.yaml",
        "QF1",
        "2026-11-03T20:00:00",
        "Y",
        {a: 1.4, b: 3.0},
    )
    snapshot(
        tmp_path / "worlds_2026_QF1_c.yaml",
        "QF1",
        "2026-11-03T22:00:00",
        "Z",
        {a: 1.1, b: 7.0},
    )
    got = score.load_odds(tmp_path, {"QF1": (a, b, start)})
    assert got["QF1"]["chosen"]["bookmaker"] == "Y"  # latest strictly before the start
    assert [r["bookmaker"] for r in got["QF1"]["rejected"]] == ["Z"]  # at/after start
    assert sum(got["QF1"]["p"].values()) == pytest.approx(1.0)


def test_odds_wrong_teams_raise(tmp_path):
    a, b = QFS[0]
    snapshot(
        tmp_path / "worlds_2026_QF1_a.yaml",
        "QF1",
        "2026-11-02T10:00:00",
        "X",
        {a: 1.5, "T1": 2.6},
    )
    with pytest.raises(ValueError):
        score.load_odds(tmp_path, {"QF1": (a, b, pd.Timestamp("2026-11-03T22:00:00"))})


def test_no_odds_files_means_skipped(tmp_path):
    assert (
        score.load_odds(
            tmp_path / "missing", {"QF1": ("a", "b", pd.Timestamp("2026-11-03"))}
        )
        == {}
    )


# ---------- results file ----------


def series_doc(a, b, pattern, start="2026-11-03T22:00:00"):
    """pattern over 'W'/'L' = the winner's result per game; first-listed team a wins;
    blue alternates, a on blue in game 1."""
    games = []
    for i, c in enumerate(pattern):
        blue = a if i % 2 == 0 else b
        games.append({"blue": blue, "winner": a if c == "W" else b})
    return {
        "start_utc": start,
        "winner": a,
        "score": [3, pattern.count("L")],
        "games": games,
    }


def full_doc():
    w = [p[0] for p in QFS]
    sf = [(w[0], w[1]), (w[2], w[3])]
    fin = (w[0], w[2])
    doc = {"series": {}}
    pats = ["WWW", "WLWW", "WLWLW", "LWWW"]
    for i, ((a, b), pat) in enumerate(zip(QFS, pats), 1):
        doc["series"][f"QF{i}"] = series_doc(a, b, pat)
    doc["series"]["SF1"] = series_doc(*sf[0], "WWLW", "2026-11-07T22:00:00")
    doc["series"]["SF2"] = series_doc(*sf[1], "WWW", "2026-11-08T22:00:00")
    doc["series"]["F"] = series_doc(*fin, "WLWLW", "2026-11-14T22:00:00")
    return doc


def blank(doc, *ids):
    d = copy.deepcopy(doc)
    for i in ids:
        d["series"][i] = {
            "start_utc": d["series"][i]["start_utc"],
            "winner": None,
            "score": None,
            "games": [],
        }
    return d


def test_parse_full_results():
    s = score.parse_results(full_doc(), CFG)
    assert [x.id for x in s] == ["QF1", "QF2", "QF3", "QF4", "SF1", "SF2", "F"]
    assert all(x.winner for x in s)
    assert (s[4].a, s[4].b) == (QFS[0][0], QFS[1][0])  # SF pair derived from QF winners
    assert (s[6].a, s[6].b) == (QFS[0][0], QFS[2][0])


def test_incomplete_results_refused():
    with pytest.raises(score.IncompleteResults, match="F"):
        score.parse_results(blank(full_doc(), "F"), CFG)


def test_incomplete_results_allowed_with_partial():
    s = score.parse_results(blank(full_doc(), "F"), CFG, partial=True)
    assert s[-1].winner is None and sum(x.winner is not None for x in s) == 6


def test_score_not_matching_games_raises():
    d = full_doc()
    d["series"]["QF2"]["score"] = [3, 2]  # games say 3-1
    with pytest.raises(ValueError, match="QF2"):
        score.parse_results(d, CFG)


def test_blue_team_outside_pair_raises():
    d = full_doc()
    d["series"]["QF1"]["games"][0]["blue"] = "T1"
    with pytest.raises(ValueError, match="QF1"):
        score.parse_results(d, CFG)


def test_game_after_series_end_raises():
    d = full_doc()
    a = QFS[0][0]
    d["series"]["QF1"]["games"].append({"blue": a, "winner": a})  # 4th win for A
    with pytest.raises(ValueError, match="QF1"):
        score.parse_results(d, CFG)


def test_semifinal_entered_before_its_quarterfinals_raises():
    d = blank(full_doc(), "QF1")
    with pytest.raises(ValueError, match="SF1"):
        score.parse_results(
            d, CFG, partial=True
        )  # SF1 has games but its pair is unknown


def test_winner_must_be_in_pair():
    d = full_doc()
    d["series"]["SF1"]["winner"] = "Gen.G"  # not in SF1
    with pytest.raises(ValueError, match="SF1"):
        score.parse_results(d, CFG)


# ---------- CSV cross-check ----------


def csv_rows(series, results, start="2026-11-04T00:00:00", league="WLDs"):
    rows = []
    t0 = pd.Timestamp(start)
    for k, (blue, winner) in enumerate(results):
        red = series[1] if blue == series[0] else series[0]
        gid = f"{series[0]}-{series[1]}-{k}"
        d = t0 + pd.Timedelta(hours=k)
        rows.append(
            {
                "gameid": gid,
                "date": d,
                "league": league,
                "teamname": blue,
                "side": "Blue",
                "result": int(winner == blue),
            }
        )
        rows.append(
            {
                "gameid": gid,
                "date": d,
                "league": league,
                "teamname": red,
                "side": "Red",
                "result": int(winner == red),
            }
        )
    return pd.DataFrame(rows)


CUTOFF = pd.Timestamp("2026-11-02T00:00:00")


def test_csv_check_verified_unverified_and_partial():
    s = score.parse_results(full_doc(), CFG)
    qf1 = s[0]
    games = csv_rows((qf1.a, qf1.b), qf1.games)
    got = score.check_against_csv(s, games, CUTOFF)
    assert got["QF1"] == "verified"
    assert got["QF2"].startswith("unverified")
    lagging = score.check_against_csv(
        s, csv_rows((qf1.a, qf1.b), qf1.games[:2]), CUTOFF
    )
    assert lagging["QF1"].startswith("partly verified")


def test_csv_check_mismatch_raises():
    s = score.parse_results(full_doc(), CFG)
    qf1 = s[0]
    wrong = [(b, w) for b, w in qf1.games]
    wrong[1] = (wrong[1][0], qf1.b if wrong[1][1] == qf1.a else qf1.a)
    with pytest.raises(ValueError, match="QF1"):
        score.check_against_csv(s, csv_rows((qf1.a, qf1.b), wrong), CUTOFF)


def test_csv_check_ignores_games_before_the_cutoff():
    s = score.parse_results(full_doc(), CFG)
    qf1 = s[0]
    old = csv_rows((qf1.a, qf1.b), [(qf1.a, qf1.b)], start="2026-10-30T00:00:00")
    assert score.check_against_csv(s, old, CUTOFF)["QF1"].startswith("unverified")


# ---------- scoring pipeline ----------


def made_up_pred():
    odds = score.bracket_odds(lambda r, a, b: 0.5, QFS, CFG["knockout"]["semifinals"])
    return {
        "meta": {"H": H, "q": Q, "sigma": SIGMA},
        "strengths": STRENGTHS,
        "odds": {t: dict(o) for t, o in odds.items()},
    }


def test_score_all_counts_and_labels():
    series = score.parse_results(full_doc(), CFG)
    rng = np.random.default_rng(0)
    out = score.score_all(made_up_pred(), CFG, series, {}, rng, NODES, 200)
    n_games = sum(len(s.games) for s in series)
    assert out["n"] == {
        "series": 7,
        "games": n_games,
        "odds_series": 0,
        "round_items": 24,
    }
    assert out["partial"] is False
    assert set(out["rounds"]) == {"semifinal", "final", "title"}
    # constant-0.5 baseline on 7 series: log 2
    assert out["series_scores"]["half"]["log_loss"] == pytest.approx(math.log(2))
    lo, hi = out["games"]["model"]["ci95"]
    assert lo <= out["games"]["model"]["log_loss"] <= hi


def test_score_all_partial_skips_title():
    series = score.parse_results(blank(full_doc(), "F"), CFG, partial=True)
    out = score.score_all(
        made_up_pred(), CFG, series, {}, np.random.default_rng(0), NODES, 50
    )
    assert out["partial"] is True
    assert out["n"]["series"] == 6
    assert set(out["rounds"]) == {"semifinal", "final"}


def test_score_all_is_reproducible_with_seeded_rng():
    series = score.parse_results(full_doc(), CFG)
    a = score.score_all(
        made_up_pred(), CFG, series, {}, np.random.default_rng(7), NODES, 200
    )
    b = score.score_all(
        made_up_pred(), CFG, series, {}, np.random.default_rng(7), NODES, 200
    )
    assert a == b


def test_score_all_odds_compared_on_same_series_only(tmp_path):
    series = score.parse_results(full_doc(), CFG)
    a, b = QFS[0]
    snapshot(
        tmp_path / "worlds_2026_QF1_a.yaml",
        "QF1",
        "2026-11-02T10:00:00",
        "X",
        {a: 1.5, b: 2.6},
    )
    odds = score.load_odds(tmp_path, {s.id: (s.a, s.b, s.start) for s in series})
    out = score.score_all(
        made_up_pred(), CFG, series, odds, np.random.default_rng(0), NODES, 50
    )
    assert out["n"]["odds_series"] == 1
    assert out["odds"]["n"] == 1
    p_a = score.margin_free({a: 1.5, b: 2.6})[a]
    assert out["odds"]["bookmaker_log_loss"] == pytest.approx(
        -math.log(p_a)
    )  # A won QF1


# ---------- writing ----------


def test_write_score_never_overwrites_and_versions(tmp_path):
    p1 = score.write_score({"x": 1}, "md1", tmp_path, "s", partial=False)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in p1}
    p2 = score.write_score({"x": 2}, "md2", tmp_path, "s", partial=False)
    assert {p.name for p in p1} == {"s.json", "s.md"}
    assert {p.name for p in p2} == {"s_v2.json", "s_v2.md"}
    for p, (data, mtime) in before.items():
        assert (p.read_bytes(), p.stat().st_mtime_ns) == (data, mtime)
    p3 = score.write_score({"x": 3}, "md3", tmp_path, "s", partial=False)
    assert p3[0].name == "s_v3.json"


def test_write_score_partial_label_does_not_take_the_full_name(tmp_path):
    p = score.write_score({}, "", tmp_path, "s", partial=True)
    assert p[0].name == "s_partial.json"
    assert score.write_score({}, "", tmp_path, "s", partial=False)[0].name == "s.json"


def test_write_score_skips_a_version_when_only_one_file_exists(tmp_path):
    (tmp_path / "s.md").write_text("old")
    p = score.write_score({}, "", tmp_path, "s", partial=False)
    assert p[0].name == "s_v2.json"
    assert (tmp_path / "s.md").read_text() == "old"


# ---------- saved prediction ----------


def small_pred(n_runs=200, seed=1):
    cfg = load_config()
    rng = np.random.default_rng(seed)
    table = run_simulation(STRENGTHS, H, Q, cfg, n_runs, rng, SIGMA)
    return cfg, {
        "meta": {"H": H, "q": Q, "sigma": SIGMA, "n_runs": n_runs, "seed": seed},
        "strengths": STRENGTHS,
        "odds": table.round(4).to_dict("index"),
    }


def test_check_prediction_accepts_a_reproducible_prediction():
    cfg, pred = small_pred()
    score.check_prediction(pred, cfg, np.random.default_rng(1))


def test_check_prediction_raises_on_mismatch():
    cfg, pred = small_pred()
    pred["odds"]["Gen.G"]["title"] += 0.01
    with pytest.raises(ValueError, match="Gen.G"):
        score.check_prediction(pred, cfg, np.random.default_rng(1))


def test_check_prediction_raises_when_config_drifts():
    cfg, pred = small_pred()
    cfg = copy.deepcopy(cfg)
    cfg["knockout"]["quarterfinals"][0] = cfg["knockout"]["quarterfinals"][0][::-1]
    cfg["rofs_game1"]["quarterfinals"] = "coin_flip"
    with pytest.raises(ValueError):
        score.check_prediction(pred, cfg, np.random.default_rng(1))


@pytest.mark.skipif(not tag_exists(), reason="tag pred-2026-preQF not in this clone")
def test_tag_config_matches_saved_prediction():
    pred = score.load_prediction(Path("results/worlds_2026_preQF.json"))
    cfg = score.tag_config("pred-2026-preQF", pred)
    assert cfg["prediction_cutoff"] == CFG["prediction_cutoff"]


@pytest.mark.skipif(not tag_exists(), reason="tag pred-2026-preQF not in this clone")
def test_tag_config_raises_on_hash_mismatch():
    pred = score.load_prediction(Path("results/worlds_2026_preQF.json"))
    pred["meta"]["config_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="config"):
        score.tag_config("pred-2026-preQF", pred)


@pytest.mark.skipif(not tag_exists(), reason="tag pred-2026-preQF not in this clone")
def test_tag_config_raises_on_commit_mismatch():
    pred = score.load_prediction(Path("results/worlds_2026_preQF.json"))
    pred["meta"]["commit"] = "0" * 40
    with pytest.raises(ValueError, match="commit"):
        score.tag_config("pred-2026-preQF", pred)


def test_load_prediction_is_read_only(tmp_path):
    p = tmp_path / "pred.json"
    p.write_text('{"meta": {}, "strengths": {}, "odds": {}}')
    before = p.stat().st_mtime_ns
    score.load_prediction(p)
    assert p.stat().st_mtime_ns == before
