from pathlib import Path

import yaml

CONFIG = Path("config")


def test_elo_config_has_required_keys():
    cfg = yaml.safe_load((CONFIG / "elo.yaml").read_text())
    for key in (
        "k_factor",
        "initial_rating",
        "decay_half_life_days",
        "simulation_count",
        "rating_noise",
        "random_seed",
        "decay_method",
    ):
        assert key in cfg, f"Missing key: {key}"
    assert cfg["decay_method"] in {"k_scale", "none"}


def test_worlds_2026_has_required_keys():
    cfg = yaml.safe_load((CONFIG / "worlds_2026.yaml").read_text())
    assert "swiss" in cfg
    assert "knockout" in cfg


def test_team_aliases_loadable():
    cfg = yaml.safe_load((CONFIG / "team_aliases.yaml").read_text())
    assert "aliases" in cfg
    assert "canonical" in cfg


def test_aliases_point_to_canonical_names():
    cfg = yaml.safe_load((CONFIG / "team_aliases.yaml").read_text())
    canonical = set(cfg["canonical"])
    for old, new in cfg["aliases"].items():
        assert new in canonical, f"{old!r} maps to unknown team {new!r}"


def test_worlds_2026_teams_are_valid():
    fmt = yaml.safe_load((CONFIG / "worlds_2026.yaml").read_text())
    canonical = set(
        yaml.safe_load((CONFIG / "team_aliases.yaml").read_text())["canonical"]
    )
    teams = fmt["teams"]
    assert isinstance(teams, list)
    assert len(teams) == len(set(teams)), "duplicate team in worlds_2026.yaml"
    assert set(teams) <= canonical, "team missing from canonical list"
    if teams:  # empty until the qualified field is confirmed
        assert len(teams) == fmt["swiss"]["total_teams"]


def test_backtest_years_configured():
    cfg = yaml.safe_load((CONFIG / "backtest.yaml").read_text())
    assert set(cfg["tournaments"]) == {2023, 2024, 2025}
    assert cfg["rating_updates"] in {"in_tournament", "frozen"}
