import pandas as pd
import pytest
import yaml

from worlds.elo import compute_ratings
from worlds.ingest import COLUMNS, ingest_report, load_games, write_processed


def game(
    gid,
    a="A",
    b="B",
    date="2024-01-01 10:00:00",
    league="LCK",
    complete="complete",
    a_wins=True,
):
    """One game as OE rows: two team rows plus one player row (must be ignored)."""
    base = {
        "gameid": gid,
        "league": league,
        "date": date,
        "patch": "14.10",
        "datacompleteness": complete,
        "playername": None,
    }
    return [
        {**base, "side": "Blue", "position": "team", "teamname": a, "result": int(a_wins)},
        {**base, "side": "Red", "position": "team", "teamname": b, "result": int(not a_wins)},
        {**base, "side": "Blue", "position": "top", "teamname": a, "result": int(a_wins),
         "playername": "p1"},
    ]  # fmt: skip


def write_csv(tmp_path, rows, name="oe.csv"):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


@pytest.fixture
def aliases(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text(
        yaml.safe_dump(
            {"canonical": ["A", "B", "C"], "aliases": {"A Old": "A", "C Old": "C"}}
        )
    )
    return path


def load(tmp_path, rows, aliases):
    return load_games(write_csv(tmp_path, rows), aliases)


def test_returns_team_rows_only_with_expected_columns(tmp_path, aliases):
    df = load(tmp_path, game("g1") + game("g2", a="B", b="C"), aliases)
    assert list(df.columns) == COLUMNS
    assert len(df) == 4
    assert df.groupby("gameid").size().eq(2).all()


def test_dates_naive_datetime_and_patch_stays_string(tmp_path, aliases):
    df = load(tmp_path, game("g1"), aliases)
    assert pd.api.types.is_datetime64_dtype(df["date"])
    assert df["date"].dt.tz is None
    assert set(df["patch"]) == {"14.10"}


@pytest.mark.parametrize("bad_date", ["not a date", None])
def test_bad_date_raises_with_gameid(tmp_path, aliases, bad_date):
    rows = game("g_ok") + game("g_bad_date", date=bad_date)
    with pytest.raises(ValueError, match="g_bad_date") as exc:
        load(tmp_path, rows, aliases)
    assert "g_ok" not in str(exc.value)


def _one_row(rows):
    return rows[:1]


def _three_rows(rows):
    return rows[:2] + [rows[0]]


def _dates_differ(rows):
    rows[1]["date"] = "2024-01-02 10:00:00"
    return rows[:2]


def _same_side(rows):
    rows[1]["side"] = "Blue"
    return rows[:2]


def _same_team(rows):
    rows[1]["teamname"] = rows[0]["teamname"]
    return rows[:2]


def _two_wins(rows):
    rows[1]["result"] = 1
    return rows[:2]


def _zero_wins(rows):
    rows[0]["result"] = 0
    return rows[:2]


@pytest.mark.parametrize(
    "corrupt",
    [
        _one_row,
        _three_rows,
        _dates_differ,
        _same_side,
        _same_team,
        _two_wins,
        _zero_wins,
    ],
)
def test_malformed_game_raises_with_gameid(tmp_path, aliases, corrupt):
    rows = game("g_ok") + corrupt(game("g_bad", a="A", b="B"))
    with pytest.raises(ValueError, match="g_bad"):
        load(tmp_path, rows, aliases)


def test_two_aliases_of_one_team_in_a_game_raise(tmp_path, aliases):
    rows = game("g_bad", a="A", b="A Old")  # both become "A" after aliasing
    with pytest.raises(ValueError, match="g_bad"):
        load(tmp_path, rows, aliases)


def test_aliases_applied_and_unknown_teams_reported_but_kept(tmp_path, aliases):
    rows = game("g1", a="A Old", b="B") + game("g2", a="Zed", b="Yak")
    df = load(tmp_path, rows, aliases)
    assert "A Old" not in set(df["teamname"])
    assert {"A", "Zed", "Yak"} <= set(df["teamname"])
    assert ingest_report(df, aliases)["unknown_teams"] == ["Yak", "Zed"]


def test_incomplete_rows_kept_and_counted_per_game_by_league(tmp_path, aliases):
    rows = (
        game("g1", league="LPL", complete="partial")
        + game("g2", league="LPL", complete="partial")
        + game("g3", league="LCK", complete="partial")
        + game("g4", league="LCK")
    )
    df = load(tmp_path, rows, aliases)
    assert len(df) == 8
    assert ingest_report(df, aliases)["incomplete_games_by_league"] == {
        "LCK": 1,
        "LPL": 2,
    }


def test_raw_csv_is_not_modified(tmp_path, aliases):
    path = write_csv(tmp_path, game("g1"))
    before = path.read_bytes()
    load_games(path, aliases)
    assert path.read_bytes() == before


def test_write_processed_roundtrip(tmp_path, aliases):
    df = load(tmp_path, game("g1"), aliases)
    out = write_processed(df, "games", out_dir=tmp_path / "processed")
    assert out == tmp_path / "processed" / "games.parquet"
    pd.testing.assert_frame_equal(pd.read_parquet(out), df)


def test_load_games_feeds_compute_ratings(tmp_path, aliases):
    rows = game("g1", date="2024-01-01 10:00:00") + game(
        "g2", a="B", b="C", date="2024-01-02 10:00:00"
    )
    df = load(tmp_path, rows, aliases)
    ratings = compute_ratings(
        df,
        pd.Timestamp("2024-02-01"),
        k=32,
        initial_rating=1500,
        decay_half_life_days=182,
        decay_method="none",
    )
    assert ratings["A"] > 1500 > ratings["C"]
    assert sum(ratings.values()) / len(ratings) == pytest.approx(1500)


def test_blank_gameid_raises(tmp_path, aliases):
    rows = game("g_ok") + game(None, a="A", b="C")
    with pytest.raises(ValueError, match="gameid"):
        load(tmp_path, rows, aliases)


def test_game_with_only_player_rows_raises(tmp_path, aliases):
    rows = game("g_ok") + [r for r in game("g_players") if r["position"] != "team"]
    with pytest.raises(ValueError, match="g_players"):
        load(tmp_path, rows, aliases)


def test_mixed_timezone_dates_raise_value_error(tmp_path, aliases):
    rows = game("g1", date="2024-01-01 10:00:00+00:00") + game(
        "g2", date="2024-01-01 10:00:00+09:00"
    )
    with pytest.raises(ValueError, match="timezone"):
        load(tmp_path, rows, aliases)


def test_report_counts_game_incomplete_if_either_row_is(tmp_path, aliases):
    rows = game("g1", league="LPL")
    rows[1]["datacompleteness"] = "partial"
    rows += game("g2", league=None, complete="partial")
    df = load(tmp_path, rows, aliases)
    counts = ingest_report(df, aliases)["incomplete_games_by_league"]
    assert counts["LPL"] == 1
    assert sum(counts.values()) == 2  # the league-less game is not dropped


def test_empty_alias_table_is_fine(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("canonical: []\naliases: {}\n")
    df = load_games(write_csv(tmp_path, game("g1")), path)
    assert ingest_report(df, path)["unknown_teams"] == ["A", "B"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n",
        "canonical: []\n",  # no aliases key
        "aliases: {}\n",  # no canonical key
        "canonical: []\naliases: [Foo]\n",  # list, not a mapping
        "canonical: []\naliases:\n  Foo:\n",  # Foo maps to nothing
        "canonical: []\naliases:\n  null: Foo\n",  # blank key would rename blank teams
        "canonical: []\naliases:\n  yes: Foo\n",  # YAML turns yes into True
        "canonical: [null, 2024]\naliases: {}\n",  # canonical items must be names
        "canonical: [[A]]\naliases: {}\n",  # unhashable item
    ],
)
def test_malformed_alias_config_raises_value_error(tmp_path, text):
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="bad.yaml"):
        load_games(write_csv(tmp_path, game("g1")), path)
    good = load_games(write_csv(tmp_path, game("g1")), _good(tmp_path))
    with pytest.raises(ValueError, match="bad.yaml"):
        ingest_report(good, path)


def _good(tmp_path):
    path = tmp_path / "good.yaml"
    path.write_text("canonical: []\naliases: {}\n")
    return path
