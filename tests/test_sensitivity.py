import copy
from pathlib import Path

import numpy as np
import pytest
import yaml

from tests.test_simulate import CFG as SIM_CFG
from tests.test_simulate import build_games, knockout_rows
from worlds import sensitivity
from worlds.bracket import game1_blue_prob
from worlds.score import series_prob
from worlds.simulate import CONFIG_FILES, games_sha256, run_simulation

OVERRIDE_PATH = Path("config/sensitivity/game1_coin_flip.yaml")
OV = yaml.safe_load(OVERRIDE_PATH.read_text())
BASE = copy.deepcopy(SIM_CFG)
VARIANT = sensitivity.apply_override(BASE, OV)
QFS = BASE["knockout"]["quarterfinals"]
TEAMS = [t for pair in QFS for t in pair]
STRENGTHS = {t: 1500.0 + 35 * i for i, t in enumerate(TEAMS)}
H, Q, SIGMA, NODES = 23.0, 0.2, 50.0, 41
TES_IG = ["Top Esports", "Invictus Gaming"]


def test_base_has_higher_seed_and_variant_has_coin_flip_for_qfs():
    assert BASE["rofs_game1"]["quarterfinals"] == "higher_seed"
    assert VARIANT["rofs_game1"]["quarterfinals"] == "coin_flip"


@pytest.mark.parametrize("a,b", QFS)
def test_variant_qf_game1_is_a_coin_flip_for_both_teams(a, b):
    assert game1_blue_prob("quarterfinals", a, b, Q, VARIANT) == 0.5
    assert game1_blue_prob("quarterfinals", b, a, Q, VARIANT) == 0.5


def test_primary_qf_game1_is_not_a_coin_flip_for_unequal_records():
    a, b = QFS[0]  # Dplus Kia 3-0 vs Bilibili Gaming 3-2
    assert game1_blue_prob("quarterfinals", a, b, Q, BASE) == Q


def test_equal_records_series_is_unchanged():
    a, b = TES_IG
    args = (a, b, "quarterfinals", STRENGTHS, H, Q, BASE, SIGMA, NODES)
    assert series_prob(*args) == series_prob(*args[:6], VARIANT, *args[7:])


@pytest.mark.parametrize("rnd", ["semifinals", "final"])
def test_later_rounds_are_unchanged(rnd):
    a, b = TEAMS[0], TEAMS[2]
    assert game1_blue_prob(rnd, a, b, Q, BASE) == game1_blue_prob(rnd, a, b, Q, VARIANT)
    args = (a, b, rnd, STRENGTHS, H, Q)
    assert series_prob(*args, BASE, SIGMA, NODES) == series_prob(
        *args, VARIANT, SIGMA, NODES
    )


def test_same_seed_same_variant_output():
    def run():
        return run_simulation(
            STRENGTHS, H, Q, VARIANT, 200, np.random.default_rng(42), SIGMA
        )

    assert run().equals(run())


def test_equal_records_pair_has_same_sf_odds_when_only_that_qf_matters():
    # TES-IG draws no RNG differently between configs: with the same seed the QF3 result stream
    # is identical, so any difference in their P(SF) can only come from other QFs via the bracket.
    # Here the other three QFs are made deterministic (huge gaps), so QF3 must be identical.
    s = {t: 1500.0 for t in TEAMS}
    for i, t in enumerate(["Dplus Kia", "Karmine Corp", "Gen.G"]):
        s[t] += 5000
    a = run_simulation(s, H, Q, BASE, 300, np.random.default_rng(7), 0.0)
    b = run_simulation(s, H, Q, VARIANT, 300, np.random.default_rng(7), 0.0)
    for t in TES_IG:
        assert a.loc[t, "semifinal"] == b.loc[t, "semifinal"]


def test_apply_override_does_not_mutate_base():
    before = copy.deepcopy(BASE)
    sensitivity.apply_override(BASE, OV)
    assert BASE == before


def test_apply_override_keeps_other_rofs_keys():
    assert VARIANT["rofs_game1"]["semifinals"] == BASE["rofs_game1"]["semifinals"]
    assert VARIANT["rofs_game1"]["final"] == BASE["rofs_game1"]["final"]


@pytest.mark.parametrize(
    "bad", [{"rofs_game1": {"quarterfinal": "coin_flip"}}, {"not_a_key": 1}]
)
def test_unknown_override_key_raises(bad):
    with pytest.raises(ValueError, match="unknown"):
        sensitivity.apply_override(BASE, {"variant": "x", **bad})


def test_override_file_is_not_part_of_the_primary_config_hash():
    assert OVERRIDE_PATH not in CONFIG_FILES
    assert not any("sensitivity" in str(p) for p in CONFIG_FILES)


def test_data_check_passes_on_the_same_pre_cutoff_data_and_ignores_post_cutoff():
    games = build_games()
    pred = {"meta": {"data_sha256": games_sha256(games, BASE)}}
    sensitivity.check_data(games, pred, BASE)
    sensitivity.check_data(build_games(extra=knockout_rows(flip=True)), pred, BASE)


def test_data_check_raises_on_changed_pre_cutoff_data():
    games = build_games()
    pred = {"meta": {"data_sha256": games_sha256(games, BASE)}}
    changed = games.copy()
    changed.loc[changed.index[0], "result"] ^= 1
    with pytest.raises(ValueError, match="data_sha256"):
        sensitivity.check_data(changed, pred, BASE)


def test_check_reproduces_raises_on_different_saved_odds():
    pred = {
        "strengths": STRENGTHS,
        "meta": {"H": H, "q": Q},
        "odds": {t: {"semifinal": 0.5, "final": 0.25, "title": 0.125} for t in TEAMS},
    }
    with pytest.raises(ValueError, match="reproduce"):
        sensitivity.check_reproduces(
            pred, {"strengths": STRENGTHS, "h": H, "q": Q, "table": _zero_table()}
        )


def _zero_table():
    import pandas as pd

    return pd.DataFrame(0.0, index=TEAMS, columns=["semifinal", "final", "title"])


def test_writer_refuses_to_overwrite_and_leaves_existing_file_untouched(tmp_path):
    sensitivity.write_new(tmp_path, "stem", {"a": 1}, "md")
    before = (tmp_path / "stem.json").read_bytes()
    with pytest.raises(FileExistsError):
        sensitivity.write_new(tmp_path, "stem", {"a": 2}, "md2")
    assert (tmp_path / "stem.json").read_bytes() == before


def test_writer_refuses_when_only_the_md_exists(tmp_path):
    (tmp_path / "stem.md").write_text("old")
    with pytest.raises(FileExistsError):
        sensitivity.write_new(tmp_path, "stem", {"a": 1}, "md")
    assert not (tmp_path / "stem.json").exists()


@pytest.mark.parametrize("stem", ["../x", "a/b", "..", "", "worlds_2026_preQF"])
def test_writer_refuses_path_stems_and_the_primary_name(tmp_path, stem):
    with pytest.raises(ValueError, match="out_stem"):
        sensitivity.write_new(tmp_path, stem, {}, "")
    assert list(tmp_path.iterdir()) == []


def test_check_reproduces_raises_on_dirty_primary_and_on_extra_teams():
    table = _zero_table()
    odds = {t: {s: 0.0 for s in table.columns} for t in TEAMS}
    res = {"strengths": STRENGTHS, "h": H, "q": Q, "table": table}
    pred = {"strengths": STRENGTHS, "meta": {"H": H, "q": Q}, "odds": odds}
    sensitivity.check_reproduces(pred, res)  # baseline passes
    with pytest.raises(ValueError, match="dirty"):
        sensitivity.check_reproduces(
            {**pred, "meta": {"H": H, "q": Q, "dirty_worktree": True}}, res
        )
    with pytest.raises(ValueError, match="reproduce"):
        sensitivity.check_reproduces(
            {**pred, "odds": dict(list(odds.items())[:-1])}, res
        )


def test_render_md_shows_both_runs_differences_and_max_title_change():
    doc = {
        "meta": {"variant": "game1_coin_flip"},
        "teams": {
            "A": {
                "primary": {"semifinal": 0.6, "final": 0.4, "title": 0.2},
                "variant": {"semifinal": 0.55, "final": 0.4, "title": 0.25},
            }
        },
        "qf_series": [
            {"a": "A", "b": "B", "primary": 0.7, "variant": 0.65},
        ],
        "max_abs_title_change": 0.05,
    }
    md = sensitivity.render_md(doc)
    assert "primary prediction unchanged" in md.lower()
    assert "-0.050" in md and "+0.050" in md
    assert "0.050" in md
