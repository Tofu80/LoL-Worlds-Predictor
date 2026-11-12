import copy
import datetime
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from worlds import export, score
from worlds import simulate as sim
from worlds.backtest import backtest_worlds
from worlds.elo import expected_score
from worlds.series import series_win_prob

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/processed/games.parquet"
FROZEN = ROOT / "results/worlds_2026_preQF.json"


def tag_exists() -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "pred-2026-preQF"],
        capture_output=True,
        check=False,
        cwd=ROOT,
    )
    return r.returncode == 0


needs_real = pytest.mark.skipif(
    not (PARQUET.exists() and tag_exists()),
    reason="needs data/processed/games.parquet and the pred-2026-preQF tag",
)


def table(rows) -> pd.DataFrame:
    """rows: (gameid, date, blue, red, blue_won) -> gameid, date, blue, red, result."""
    return pd.DataFrame(
        [
            {
                "gameid": g,
                "date": pd.Timestamp(d),
                "blue": b,
                "red": r,
                "result": int(w),
            }
            for g, d, b, r, w in rows
        ]
    )


# ---------- series ----------


def test_series_group_by_pair_and_gap():
    t = table(
        [
            ("g1", "2024-10-01 10:00", "A", "B", True),
            ("g2", "2024-10-01 11:00", "B", "A", True),  # same series, sides swapped
            ("g3", "2024-10-01 12:00", "A", "B", False),
            ("g4", "2024-10-01 10:30", "C", "D", True),
            ("g5", "2024-10-05 10:00", "A", "B", True),  # same pair, days later
        ]
    )
    s = export.build_series(t, gap_hours=4)
    assert [(x["a"], x["b"], len(x["games"])) for x in s] == [
        ("A", "B", 3),
        ("C", "D", 1),
        ("A", "B", 1),
    ]
    assert s[0]["wins"] == {"A": 1, "B": 2}
    assert export.winner_of(s[0]) == "B"
    assert [export.series_format(x) for x in s] == ["bo3", "bo1", "bo1"]


@pytest.mark.parametrize(
    "results,fmt",
    [([1], "bo1"), ([1, 1], "bo3"), ([1, 0, 1], "bo3"), ([1, 1, 1], "bo5")],
)
def test_series_format_from_winner_wins(results, fmt):
    rows = [
        (f"g{i}", f"2024-10-01 1{i}:00", "A", "B", bool(r))
        for i, r in enumerate(results)
    ]
    assert export.series_format(export.build_series(table(rows), 4)[0]) == fmt


@pytest.mark.parametrize("results", [[1, 0], [1, 0, 1, 0], [1, 1, 1, 1]])
def test_odd_series_scores_raise(results):
    rows = [
        (f"g{i}", f"2024-10-01 1{i}:00", "A", "B", bool(r))
        for i, r in enumerate(results)
    ]
    with pytest.raises(ValueError, match="odd score"):
        export.series_format(export.build_series(table(rows), 4)[0])


def fake_series(stage_starts):
    return [
        {"a": "A", "b": "B", "start": pd.Timestamp(d), "result": {"winner": "A"}}
        for d in stage_starts
    ]


def test_label_stages_play_in_swiss_and_knockout():
    s = fake_series(
        ["2024-09-26", "2024-10-04"] + [f"2024-10-{d}" for d in range(17, 24)]
    )
    export.label_stages(s, pd.Timestamp("2024-10-03"), pd.Timestamp("2024-10-17"))
    assert [x["stage"] for x in s] == (
        ["play-in", "swiss"] + ["quarterfinal"] * 4 + ["semifinal"] * 2 + ["final"]
    )


def test_label_stages_wrong_knockout_count_raises():
    s = fake_series(["2024-10-04", "2024-10-17", "2024-10-18"])
    with pytest.raises(ValueError, match="knockout series"):
        export.label_stages(s, pd.Timestamp("2024-10-03"), pd.Timestamp("2024-10-17"))


def test_label_stages_without_knockout_start_is_all_swiss():
    s = fake_series(["2026-10-15", "2026-10-24", "2026-10-30"])
    export.label_stages(s, pd.Timestamp("2026-10-23"))
    assert [x["stage"] for x in s] == ["play-in", "swiss", "swiss"]


def test_check_swiss():
    ok = {f"adv{i}": [3, i % 3] for i in range(8)} | {
        f"out{i}": [i % 3, 3] for i in range(8)
    }
    export.check_swiss(ok, 2024)
    bad = dict(ok, adv0=[2, 2])
    with pytest.raises(ValueError, match="stage dates"):
        export.check_swiss(bad, 2024)
    with pytest.raises(ValueError, match="stage dates"):
        export.check_swiss({k: v for k, v in ok.items() if k != "out0"}, 2024)


def test_swiss_records_count_series_not_games():
    s = fake_series(["2024-10-04", "2024-10-05"])
    for x in s:
        x["stage"] = "swiss"
    s[1]["a"], s[1]["b"], s[1]["result"]["winner"] = "A", "C", "C"
    assert export.swiss_records(s) == {"A": [1, 1], "B": [0, 1], "C": [1, 0]}


# ---------- walk-forward probabilities ----------


def test_neutral_series_p():
    assert export.neutral_series_p(1500, 1500, 30.0, "bo5") == pytest.approx(0.5)
    p = 0.5 * (expected_score(1600, 1500, 25.0) + expected_score(1600, 1500, -25.0))
    assert export.neutral_series_p(1600, 1500, 25.0, "bo3") == pytest.approx(
        series_win_prob(p, "bo3")
    )
    assert export.neutral_series_p(1700, 1500, 25.0, "bo3") > export.neutral_series_p(
        1600, 1500, 25.0, "bo3"
    )


CONFIG = {
    "k_factor": 32,
    "initial_rating": 1500,
    "decay_half_life_days": 182,
    "decay_method": "none",
    "rating_updates": "in_tournament",
    "tournaments": {2025: {"start_date": datetime.date(2025, 10, 14)}},
}
CUTOFF = pd.Timestamp("2025-10-14")


def make_games(rows) -> pd.DataFrame:
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


def worlds_games(results):
    """A pre-start game, then a Bo1, a Bo3 and a Bo1 at Worlds; results = 7 bools."""
    r = list(results)
    return make_games(
        [
            ("p0", "2025-10-01 12:00", "LEC", "A", "B", True),
            ("w1", "2025-10-14 12:00", "WLDs", "A", "B", r[0]),
            ("w2", "2025-10-16 12:00", "WLDs", "A", "C", r[1]),
            ("w3", "2025-10-16 13:00", "WLDs", "C", "A", r[2]),
            ("w4", "2025-10-16 14:00", "WLDs", "A", "C", r[3]),
            ("w5", "2025-10-20 12:00", "WLDs", "B", "C", r[4]),
            ("w6", "2025-10-22 12:00", "WLDs", "A", "B", r[5]),
            ("w7", "2025-10-24 12:00", "WLDs", "C", "A", r[6]),
        ]
    )


def run_wf(results, h=0.0):
    res = backtest_worlds(2025, worlds_games(results), CONFIG, CUTOFF, record=True)
    return export.walk_forward_matches(res.predictions, res.history, h, 4), res


BASE = [True, True, True, True, True, False, True]  # w2-w4: A wins 2-1


def test_walk_forward_series_values():
    ms, res = run_wf(BASE)
    assert [m["format"] for m in ms] == ["bo1", "bo3", "bo1", "bo1", "bo1"]
    bo3 = ms[1]
    assert bo3["result"] == {"status": "final", "winner": "A", "score": [2, 1]}
    sa = bo3["assumptions"]["strength_a"]
    sb = bo3["assumptions"]["strength_b"]
    assert bo3["p_a"] == pytest.approx(export.neutral_series_p(sa, sb, 0.0, "bo3"))
    assert bo3["log_loss"] == pytest.approx(-math.log(bo3["p_a"]))
    bo1 = ms[0]
    assert bo1["p_a"] == bo1["games"][0]["p_blue"]  # a Bo1 is its own game
    for m in ms:
        assert m["provenance"] == "walk_forward"
        assert {g["provenance"] for g in m["games"]} == {"walk_forward"}
    # per-game rows are the backtest's own predictions
    flat = [g["p_blue"] for m in ms for g in m["games"]]
    assert flat == res.predictions.sort_values("date")["p_blue"].tolist()


def test_perturbing_later_results_changes_no_earlier_probability():
    """Flip every result after game t: all game and series probabilities up to t stay."""
    base, _ = run_wf(BASE)
    for t in range(1, 7):  # t = index of the last unchanged game (w1..w7 -> 0..6)
        flipped = [r if i <= t else (not r) for i, r in enumerate(BASE)]
        alt, _ = run_wf(flipped)
        g0 = [g for m in base for g in m["games"]]
        g1 = [g for m in alt for g in m["games"]]
        assert [g["p_blue"] for g in g0[: t + 1]] == [g["p_blue"] for g in g1[: t + 1]]
        # a series starting at or before game t has its probability from ratings before
        # its first game, so it is unchanged even if its own later games were flipped
        started = 0
        for m, n in zip(base, alt):
            if m["games"][0]["gameid"] in {g["gameid"] for g in g0[: t + 1]}:
                assert m["p_a"] == n["p_a"]
                started += 1
        assert started >= 1
    assert [m["p_a"] for m in base] != [
        m["p_a"] for m in run_wf([not r for r in BASE])[0]
    ]


# ---------- helpers ----------


def test_clean_rounds_converts_and_rejects_nan():
    x = {
        "t": pd.Timestamp("2025-10-14 12:00:30"),
        "p": np.float64(0.123456),
        "n": np.int64(3),
    }
    assert export.clean(x, 4) == {"t": "2025-10-14T12:00", "p": 0.1235, "n": 3}
    assert export.clean(0.123456, None) == 0.123456
    with pytest.raises(ValueError):
        export.clean({"p": float("nan")})


def test_slugify():
    assert export.slugify("Gen.G") == "gen-g"
    assert export.slugify("LØS") == "los"
    assert export.slugify("Team Liquid Alienware") == "team-liquid-alienware"
    assert export.slugify("Anyone's Legend") == "anyone-s-legend"


def test_pick_score_file_prefers_complete_then_highest_version(tmp_path):
    def put(name, partial):
        (tmp_path / name).write_text(json.dumps({"partial": partial}))

    pattern = str(tmp_path / "worlds_2026_preQF_score*.json")
    assert export.pick_score_file(pattern) is None
    put("worlds_2026_preQF_score_partial.json", True)
    put("worlds_2026_preQF_score_partial_v2.json", True)
    assert export.pick_score_file(pattern).name.endswith("partial_v2.json")
    put("worlds_2026_preQF_score.json", False)
    assert export.pick_score_file(pattern).name == "worlds_2026_preQF_score.json"
    put("worlds_2026_preQF_score_v2.json", False)
    assert export.pick_score_file(pattern).name == "worlds_2026_preQF_score_v2.json"


# ---------- real frozen prediction, tagged config ----------


@pytest.fixture(scope="module")
def frozen():
    pred = score.load_prediction(FROZEN)
    return pred, score.tag_config("pred-2026-preQF", pred)


def starts_none():
    return dict.fromkeys(score.IDS)


COMMITTED = pd.Timestamp("2026-11-10T11:52:38")


@needs_real
def test_knockout_pending_without_score_output(frozen):
    pred, cfg_tag = frozen
    ko = export.knockout_matches(pred, cfg_tag, 41, None, starts_none(), COMMITTED)
    assert [m["id"] for m in ko] == [f"2026-{i}" for i in score.IDS]
    qf, rest = ko[:4], ko[4:]
    for m in qf:
        assert m["provenance"] == "frozen"
        assert m["derivation"] == "computed_from_frozen_inputs"
        assert m["result"] == {"status": "pending"}
        assert 0 < m["p_a"] < 1
        assert "games" not in m
    assert [(m["a"], m["b"]) for m in qf] == [
        tuple(p) for p in cfg_tag["knockout"]["quarterfinals"]
    ]
    assert all(m["a"] is None and m["p_a"] is None for m in rest)
    # the saved sim odds and the quadrature agree to Monte Carlo error (n_runs = 10000)
    sens = json.loads(
        (ROOT / "results/worlds_2026_preQF_sens_game1coin.json").read_text()
    )
    assert qf[0]["p_a"] == pytest.approx(sens["qf_series"][0]["primary"], abs=1e-9)


@needs_real
def test_knockout_with_a_finished_series(frozen):
    pred, cfg_tag = frozen
    a, b = cfg_tag["knockout"]["quarterfinals"][0]
    m_ = pred["meta"]
    p = score.series_prob(
        a,
        b,
        "quarterfinals",
        pred["strengths"],
        m_["H"],
        m_["q"],
        cfg_tag,
        m_["sigma"],
        41,
    )
    doc = {
        "series": [
            {
                "series": "QF1",
                "a": a,
                "b": b,
                "winner": b,
                "score": [3, 1],
                "p_a_model": p,
                "a_won": 0,
            }
        ],
        "games": {
            "rows": [
                {
                    "series": "QF1",
                    "game": n,
                    "blue": a,
                    "red": b,
                    "p_blue_model": 0.5,
                    "blue_won": w,
                }
                for n, w in enumerate([0, 1, 0, 0], 1)
            ]
        },
    }
    starts = {**starts_none(), "QF1": pd.Timestamp("2026-11-03T22:00")}
    ko = export.knockout_matches(pred, cfg_tag, 41, doc, starts, COMMITTED)
    m = ko[0]
    assert m["result"] == {"status": "final", "winner": b, "score": [3, 1]}
    assert m["log_loss"] == pytest.approx(-math.log(1 - p))
    assert [g["blue_won"] for g in m["games"]] == [0, 1, 0, 0]
    assert {g["provenance"] for g in m["games"]} == {"frozen"}
    assert m["played_before_commit"] is True
    assert ko[1]["played_before_commit"] is None  # not finished, start not entered
    with pytest.raises(ValueError, match="no start_utc"):
        export.knockout_matches(pred, cfg_tag, 41, doc, starts_none(), COMMITTED)
    stale = copy.deepcopy(doc)
    stale["series"][0]["p_a_model"] = p + 0.01
    with pytest.raises(ValueError, match="stale score file"):
        export.knockout_matches(pred, cfg_tag, 41, stale, starts, COMMITTED)


@needs_real
def test_integrity_rejects_a_changed_pre_cutoff_data_hash():
    cfg26 = sim.load_config()
    pred = score.load_prediction(FROZEN)
    games = sim._before_cutoff(pd.read_parquet(PARQUET), cfg26)
    export.integrity(games, cfg26, pred)  # reproduces the frozen strengths
    bad = copy.deepcopy(pred)
    bad["meta"]["data_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="data_sha256"):
        export.integrity(games, cfg26, bad)
    bad = copy.deepcopy(pred)
    bad["strengths"]["Gen.G"] += 1.0
    with pytest.raises(ValueError, match="differ from the frozen"):
        export.integrity(games, cfg26, bad)


# ---------- the whole export on real data ----------

ALLOWED_KEYS = {
    "+H",
    "+H+league",
    "0.5",
    "16",
    "2023",
    "2024",
    "2025",
    "2026",
    "32",
    "64",
    "8",
    "H",
    "a",
    "assumptions",
    "b",
    "bin",
    "blue",
    "blue-only",
    "blue_won",
    "bootstrap_samples",
    "bootstrap_vs_current",
    "bracket",
    "brier",
    "calibration",
    "calibration_by_class",
    "chosen",
    "columns",
    "commit",
    "committed_utc",
    "computed_from_frozen_inputs",
    "config",
    "config_sha256",
    "current",
    "current_2025",
    "current_pooled",
    "data_sha256",
    "data_source",
    "date",
    "decay_half_life_days",
    "derivation",
    "derivation_text",
    "dirty_worktree",
    "final",
    "format",
    "frozen",
    "gameid",
    "games",
    "generated_at",
    "grid_pooled_2023_24",
    "h",
    "hi",
    "history",
    "id",
    "initial_rating",
    "k_factor",
    "k_league",
    "label",
    "league",
    "league_offset",
    "legend",
    "lo",
    "log_loss",
    "major-major",
    "major-minor",
    "matches",
    "max_abs_title_change",
    "mean",
    "mean_pred",
    "merge_bar",
    "minor-minor",
    "model",
    "n",
    "n_runs",
    "name",
    "note",
    "observed",
    "ok",
    "p_a",
    "p_a_frozen",
    "p_blue",
    "path_to_title",
    "per_year",
    "played_before_commit",
    "points",
    "pooled",
    "prediction_cutoff_utc",
    "provenance",
    "q",
    "qf_series",
    "quarterfinals",
    "rating",
    "red",
    "result",
    "same-league",
    "saved",
    "schema_version",
    "score",
    "seasons",
    "seed",
    "semifinal",
    "semifinals",
    "sensitivity",
    "series_model",
    "side",
    "side_advantage_window_days",
    "sigma",
    "slug",
    "stage",
    "stage_reached",
    "start",
    "status",
    "strength",
    "strength_a",
    "strength_b",
    "swiss_record",
    "tag",
    "team",
    "teams",
    "title",
    "variant",
    "as_of",
    "k_league_in_sample",
    "output_commit",
    "prediction_sha256",
    "variants",
    "walk_forward",
    "walk_forward_replay",
    "winner",
    "worlds",
    "y2025",
    "year",
    "years",
}

FORBIDDEN = {
    "playername", "playerid", "position", "champion", "patch", "datacompleteness",
    "kills", "deaths", "assists", "gold", "ban1", "pick1", "split", "url",
}  # fmt: skip
PROB_KEYS = {"p_a", "p_blue", "semifinal", "final", "title"}


def walk(x, under_provenance=False, out=None):
    """Yield (dict, has_provenance_on_the_path) for every dict in a JSON value."""
    out = [] if out is None else out
    if isinstance(x, dict):
        here = under_provenance or "provenance" in x
        out.append((x, here))
        for v in x.values():
            walk(v, here, out)
    elif isinstance(x, list):
        for v in x:
            walk(v, under_provenance, out)
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not (PARQUET.exists() and tag_exists()):
        pytest.skip("needs games.parquet and the pred-2026-preQF tag")
    exp = export.load_export_config()
    cfg26 = sim.load_config()
    pred = score.load_prediction(FROZEN)
    args = {
        "exp": exp,
        "bcfg": export.bt.load_config(),
        "cfg26": cfg26,
        "pred": pred,
        "sens": json.loads(Path(exp["sensitivity"]).read_text()),
        "cfg_tag": score.tag_config(exp["frozen_tag"], pred),
        "doc": None,
        "doc_name": None,
        "starts": starts_none(),
        "nodes": yaml.safe_load(export.SCORE_CONFIG_PATH.read_text())[
            "quadrature_nodes"
        ],
    }
    games = pd.read_parquet(PARQUET)
    files = export.build_all(games, **args)
    return files, games, args, tmp_path_factory.mktemp("site")


@needs_real
def test_schema_and_files(built):
    files, _, _, tmp = built
    assert {"matches.json", "model.json", "overview_2026.json", "meta.json"} <= set(
        files
    )
    assert "teams/index.json" in files
    meta = files["meta.json"]
    assert meta["schema_version"] == 1
    assert {"generated_at", "legend", "data_sha256"} <= set(meta)
    assert set(meta["legend"]) == set(export.PROVENANCE)
    idx = files["teams/index.json"]["teams"]
    assert len(idx) == len({t["slug"] for t in idx}) >= 30
    for t in idx:
        f = files[f"teams/{t['slug']}.json"]
        assert {
            "name",
            "league",
            "league_offset",
            "worlds",
            "history",
            "matches",
        } <= set(f)
        assert f["history"]["columns"] == export.HISTORY_COLUMNS
        assert all(
            len(p) == len(export.HISTORY_COLUMNS) for p in f["history"]["points"]
        )
    ms = files["matches.json"]["matches"]
    assert len({m["id"] for m in ms}) == len(ms)
    need = {"id", "year", "stage", "format", "a", "b", "provenance", "p_a", "result"}
    assert all(need <= set(m) for m in ms)
    total = export.write_files(files, tmp)
    assert total < 2_000_000  # small enough to commit
    assert (
        json.loads((tmp / "matches.json").read_text())["matches"][0]["id"]
        == ms[0]["id"]
    )


@needs_real
def test_every_probability_has_a_provenance(built):
    files, *_ = built
    seen = 0
    for rel, obj in files.items():
        for d, has in walk(obj):
            if PROB_KEYS & set(d) and rel != "meta.json":
                seen += 1
                assert has, f"{rel}: {sorted(PROB_KEYS & set(d))} without provenance"
    assert seen > 500
    for rel, obj in files.items():
        for d, _ in walk(obj):
            if "provenance" in d:
                assert d["provenance"] in export.PROVENANCE
            if "derivation" in d and d["derivation"] is not None:
                assert d["derivation"] in export.DERIVATION


@needs_real
def test_frozen_numbers_equal_the_tagged_json(built):
    """The saved file is committed after its tag's commit, so the comparison is with the
    blob of the pinned output commit; its meta.commit is the tag's commit (score.tag_config
    raised in the fixture otherwise)."""
    files, _, args, _ = built
    exp = args["exp"]
    if subprocess.run(
        ["git", "cat-file", "-e", exp["frozen_output_commit"]], cwd=ROOT, check=False
    ).returncode:
        pytest.skip("pinned output commit not in this clone")
    tagged = json.loads(
        subprocess.run(
            [
                "git",
                "show",
                f"{exp['frozen_output_commit']}:results/worlds_2026_preQF.json",
            ],
            capture_output=True,
            check=True,
            cwd=ROOT,
        ).stdout
    )
    ov = files["overview_2026.json"]
    assert {t["team"] for t in ov["teams"]} == set(tagged["odds"])
    for t in ov["teams"]:
        assert t["strength"] == tagged["strengths"][t["team"]]
        for stage in ("semifinal", "final", "title"):
            assert t[stage] == tagged["odds"][t["team"]][stage]
        assert t["provenance"] == "frozen"
    assert (
        hashlib.sha256((ROOT / exp["frozen_prediction"]).read_bytes()).hexdigest()
        == exp["frozen_prediction_sha256"]
    )
    assert ov["frozen"]["H"] == tagged["meta"]["H"]
    assert ov["frozen"]["q"] == tagged["meta"]["q"]
    # path_to_title on the team pages is the same saved number
    for team, odds in tagged["odds"].items():
        page = files[f"teams/{export.slugify(team)}.json"]
        assert {k: page["path_to_title"][k] for k in odds} == odds


@needs_real
def test_2026_walk_forward_stops_before_the_cutoff(built):
    files, _, args, _ = built
    cutoff = pd.Timestamp(args["cfg26"]["prediction_cutoff"])
    n_wf = 0
    for m in files["matches.json"]["matches"]:
        if m["year"] == 2026 and m["provenance"] == "walk_forward":
            n_wf += 1
            assert m["stage"] in ("play-in", "swiss")
            assert all(pd.Timestamp(g["date"]) < cutoff for g in m["games"])
        if m["year"] == 2026 and m["stage"] in ("quarterfinal", "semifinal", "final"):
            assert m["provenance"] == "frozen"
    assert n_wf > 30
    # history stops at the last Swiss game
    for t in files["teams/index.json"]["teams"]:
        pts = files[f"teams/{t['slug']}.json"]["history"]["points"]
        assert all(pd.Timestamp(p[0]) < cutoff for p in pts)


@needs_real
def test_post_cutoff_rows_change_nothing(built):
    """Flip every 2026 result from the cutoff on (knockout and other games): same output."""
    files, games, args, _ = built
    cutoff = pd.Timestamp(args["cfg26"]["prediction_cutoff"])
    alt = games.copy()
    late = alt["date"] >= cutoff
    alt.loc[late, "result"] = 1 - alt.loc[late, "result"]
    again = export.build_all(alt, **args)
    for rel in files:
        a, b = copy.deepcopy(files[rel]), copy.deepcopy(again[rel])
        if rel == "meta.json":
            a.pop("generated_at"), b.pop("generated_at")
        assert a == b, rel


@needs_real
def test_only_whitelisted_team_level_keys(built):
    files, *_ = built
    names = {t["name"] for t in files["teams/index.json"]["teams"]}
    keys = set()
    for obj in files.values():
        for d, _ in walk(obj):
            keys |= set(d)
    keys -= names
    assert not keys & FORBIDDEN
    assert keys <= ALLOWED_KEYS, (
        f"new keys need a decision: {sorted(keys - ALLOWED_KEYS)}"
    )
    # no gameid except for Worlds games, and no player-level or raw-row fields
    worlds_ids = {
        g["gameid"]
        for m in files["matches.json"]["matches"]
        for g in m.get("games", [])
        if "gameid" in g
    }
    for t in files["teams/index.json"]["teams"]:
        for p in files[f"teams/{t['slug']}.json"]["history"]["points"]:
            assert p[5] is None or p[5] in worlds_ids


@needs_real
def test_stage_dates_reproduce_the_swiss_format(built):
    files, *_ = built
    for year in (2023, 2024, 2025):
        stages = [
            m["stage"] for m in files["matches.json"]["matches"] if m["year"] == year
        ]
        assert stages.count("quarterfinal") == 4
        assert stages.count("semifinal") == 2
        assert stages.count("final") == 1


@needs_real
def test_model_json_matches_the_backtest(built):
    files, *_ = built
    v = files["model.json"]["variants"]
    assert round(v["current"]["pooled"]["log_loss"], 4) == 0.7045
    assert round(v["+H"]["pooled"]["log_loss"], 4) == 0.6998
    assert round(v["+H+league"]["pooled"]["log_loss"], 4) == 0.6614
    assert round(v["0.5"]["pooled"]["log_loss"], 4) == 0.6931
    assert files["model.json"]["k_league"]["chosen"] == 64
    n = sum(m["pooled"]["n"] for m in [v["+H+league"]])
    assert n == 300
    # the exported games reproduce the pooled log loss
    ll = [
        g["log_loss"]
        for m in files["matches.json"]["matches"]
        if m["year"] < 2026
        for g in m["games"]
    ]
    assert len(ll) == 300 and round(float(np.mean(ll)), 4) == 0.6614


@needs_real
def test_git_meta_records_code_and_frozen_identity():
    exp = export.load_export_config()
    pred = score.load_prediction(FROZEN)
    m = export.git_meta(exp, pred)
    assert len(m["commit"]) == 40 and isinstance(m["dirty_worktree"], bool)
    assert m["frozen"]["commit"] == pred["meta"]["commit"]
    assert m["frozen"]["committed_utc"] == "2026-11-10T11:52"


def test_check_pinned_and_score_results(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{}")
    sha = hashlib.sha256(b"{}").hexdigest()
    export.check_pinned(f, sha, "file")
    with pytest.raises(ValueError, match="pins"):
        export.check_pinned(f, "0" * 64, "file")
    export.check_score_results({"meta": {"results_sha256": sha}}, f)
    with pytest.raises(ValueError, match="run worlds.score again"):
        export.check_score_results({"meta": {"results_sha256": "0" * 64}}, f)


def test_game1_probability_must_be_reproduced_by_the_snapshots():
    res = backtest_worlds(2025, worlds_games(BASE), CONFIG, CUTOFF, record=True)
    export.walk_forward_matches(res.predictions, res.history, 0.0, 4)  # fine
    with pytest.raises(ValueError, match="ratings before game 1"):
        export.walk_forward_matches(res.predictions, res.history, 10.0, 4)


def test_legends_take_dates_from_the_files():
    exp = {
        "frozen_committed_utc": pd.Timestamp("2026-11-10T11:52:38"),
        "frozen_tag": "T",
        "frozen_output_commit": "abc1234",
    }
    pred = {"meta": {"prediction_cutoff_utc": "2026-11-02T00:00:00"}}
    legend, der = export.legends(exp, pred, datetime.datetime(2027, 1, 5, 3, 0))
    assert "before 2026-11-02" in legend["frozen"] and "2026-11-10" in legend["frozen"]
    assert "abc1234" in legend["frozen"]
    assert "2027-01-05" in der["computed_from_frozen_inputs"]
    assert "not saved on 2026-11-10" in der["computed_from_frozen_inputs"]
    assert "k_league was chosen on the 2023-24 results" in legend["walk_forward"]


@needs_real
def test_in_sample_flag_and_as_of(built):
    files, *_ = built
    for m in files["matches.json"]["matches"]:
        if m["provenance"] == "walk_forward":
            assert m["assumptions"]["k_league_in_sample"] == (m["year"] in (2023, 2024))
    t = files["teams/gen-g.json"]
    assert t["as_of"] == t["history"]["points"][-1][0]
