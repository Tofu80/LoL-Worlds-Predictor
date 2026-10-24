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


def test_backtest_start_dates_set_and_usable_as_timestamps():
    import pandas as pd

    cfg = yaml.safe_load((CONFIG / "backtest.yaml").read_text())
    starts = {y: pd.Timestamp(t["start_date"]) for y, t in cfg["tournaments"].items()}
    assert starts == {
        2023: pd.Timestamp("2023-10-10"),
        2024: pd.Timestamp("2024-09-25"),
        2025: pd.Timestamp("2025-10-14"),
    }


def test_data_exclusions_and_ingest_config_load():
    ex = yaml.safe_load((CONFIG / "data_exclusions.yaml").read_text())["exclusions"]
    assert {e["gameid"] for e in ex} >= {
        "ESPORTSTMNT01_3408461",
        "LOLTMNT01_52116",
    }
    intl = yaml.safe_load((CONFIG / "ingest.yaml").read_text())["international_leagues"]
    assert {"WLDs", "MSI", "FST", "EWC"} <= set(intl)


def test_alias_names_are_not_also_canonical():
    cfg = yaml.safe_load((CONFIG / "team_aliases.yaml").read_text())
    both = set(cfg["aliases"]) & set(cfg["canonical"])
    assert not both, f"alias key is also canonical: {sorted(both)}"


def test_league_alias_targets_are_not_canonical_and_not_worlds_teams():
    cfg = yaml.safe_load((CONFIG / "team_aliases.yaml").read_text())
    rules = cfg.get("league_aliases") or []
    assert any(r["from"] == "Movistar KOI" for r in rules)
    targets = {r["to"] for r in rules}
    assert not targets & set(cfg["canonical"])
    teams = yaml.safe_load((CONFIG / "worlds_2026.yaml").read_text())["teams"]
    assert not targets & set(teams)
