import pandas as pd
import pytest
import yaml

from worlds.elo import compute_ratings
from worlds.ingest import COLUMNS, ingest_report, load_games, write_processed

INTL = ["WLDs"]  # explicit, so tests don't depend on config/ingest.yaml


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


@pytest.fixture
def exclusions(tmp_path):
    path = tmp_path / "exclusions.yaml"
    entry = {"gameid": "g_void", "reason": "both team rows have result 0"}
    path.write_text(yaml.safe_dump({"exclusions": [entry]}))
    return path


def load(tmp_path, rows, aliases, exclusions=None):
    kwargs = {} if exclusions is None else {"exclusions_path": exclusions}
    return load_games(write_csv(tmp_path, rows), aliases, **kwargs)


def report(df, aliases, intl=INTL, required=(), **kw):
    return ingest_report(
        df, aliases, international_leagues=intl, required_teams=list(required), **kw
    )


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


def test_aliases_applied_and_unknown_international_teams_reported_but_kept(
    tmp_path, aliases
):
    rows = game("g1", a="A Old", b="B") + game("g2", a="Zed", b="Yak", league="WLDs")
    df = load(tmp_path, rows, aliases)
    assert "A Old" not in set(df["teamname"])
    assert {"A", "Zed", "Yak"} <= set(df["teamname"])
    assert report(df, aliases)["unknown_teams"] == ["Yak", "Zed"]


def test_incomplete_rows_kept_and_counted_per_game_by_league(tmp_path, aliases):
    rows = (
        game("g1", league="LPL", complete="partial")
        + game("g2", league="LPL", complete="partial")
        + game("g3", league="LCK", complete="partial")
        + game("g4", league="LCK")
    )
    df = load(tmp_path, rows, aliases)
    assert len(df) == 8
    assert report(df, aliases)["incomplete_games_by_league"] == {
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
    counts = report(df, aliases)["incomplete_games_by_league"]
    assert counts["LPL"] == 1
    assert sum(counts.values()) == 2  # the league-less game is not dropped


def test_empty_alias_table_is_fine(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("canonical: []\naliases: {}\n")
    df = load_games(write_csv(tmp_path, game("g1")), path)
    assert report(df, path, required=["A", "B"])["unknown_teams"] == ["A", "B"]


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
        report(good, path)


def _good(tmp_path):
    path = tmp_path / "good.yaml"
    path.write_text("canonical: []\naliases: {}\n")
    return path


# --- data exclusions (decision 1)


def void_game(gid="g_void"):
    rows = game(gid)
    rows[0]["result"] = 0  # both team rows now 0
    return rows


def test_listed_void_game_is_dropped_and_reported(tmp_path, aliases, exclusions):
    df = load(tmp_path, game("g1") + void_game(), aliases, exclusions)
    assert set(df["gameid"]) == {"g1"}
    rep = report(df, aliases, exclusions_path=exclusions)
    assert rep["excluded_games"] == {"g_void": "both team rows have result 0"}
    assert rep["exclusions_not_found"] == []


def test_unlisted_void_game_still_raises(tmp_path, aliases, exclusions):
    rows = game("g1") + void_game("g_other_void")
    with pytest.raises(ValueError, match="g_other_void"):
        load(tmp_path, rows, aliases, exclusions)


def test_listed_gameid_not_in_file_is_reported_not_found(tmp_path, aliases, exclusions):
    df = load(tmp_path, game("g1"), aliases, exclusions)
    rep = report(df, aliases, exclusions_path=exclusions)
    assert rep["excluded_games"] == {}
    assert rep["exclusions_not_found"] == ["g_void"]


def test_exclusion_dropped_in_another_file_is_not_reported_missing(
    tmp_path, aliases, exclusions
):
    df = load(tmp_path, game("g1"), aliases, exclusions)
    rep = report(df, aliases, exclusions_path=exclusions, excluded_gameids={"g_void"})
    assert rep["exclusions_not_found"] == []
    assert rep["excluded_games"] == {"g_void": "both team rows have result 0"}


def test_exclusion_drops_only_the_listed_game(tmp_path, aliases, exclusions):
    df = load(tmp_path, void_game() + game("g2"), aliases, exclusions)
    assert set(df["gameid"]) == {"g2"}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "exclusions: {}\n",
        "exclusions: [g1]\n",
        "exclusions:\n  - {gameid: g1}\n",  # no reason
        "exclusions:\n  - {gameid: g1, reason: ''}\n",
        "exclusions:\n  - {gameid: 12, reason: x}\n",
        "exclusions:\n  - {gameid: g1, reason: x}\n  - {gameid: g1, reason: y}\n",
    ],
)
def test_malformed_exclusions_config_raises_value_error(tmp_path, aliases, text):
    path = tmp_path / "badx.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="badx.yaml"):
        load(tmp_path, game("g1"), aliases, path)


def test_empty_exclusions_list_is_fine(tmp_path, aliases):
    path = tmp_path / "x.yaml"
    path.write_text("exclusions: []\n")
    assert len(load(tmp_path, game("g1"), aliases, path)) == 2


# --- timestamps, not calendar dates (decision 2)


@pytest.mark.parametrize(
    ("cutoff", "expected_teams"),
    [
        ("2026-10-23 20:00", set()),  # 00:30 UTC next day is after this cutoff
        ("2026-10-24 01:00", {"A", "B"}),  # and before this one, same calendar day
        ("2026-10-24 00:30:00", set()),  # at the cutoff is not "before" it
    ],
)
def test_game_after_midnight_utc_is_compared_by_timestamp(
    tmp_path, aliases, cutoff, expected_teams
):
    df = load(tmp_path, game("g1", date="2026-10-24 00:30:00"), aliases)
    ratings = compute_ratings(df, pd.Timestamp(cutoff), 32, 1500, 182, "none")
    assert set(ratings) == expected_teams


def test_evening_game_is_not_before_a_date_only_cutoff_of_that_day(tmp_path, aliases):
    df = load(tmp_path, game("g1", date="2026-10-23 20:00:00"), aliases)
    ratings = compute_ratings(df, pd.Timestamp("2026-10-23"), 32, 1500, 182, "none")
    assert ratings == {}


# --- canonical scope (decision 3)


def test_unknown_domestic_team_passes_through_and_is_counted(tmp_path, aliases):
    rows = game("g1", a="Zed", b="Yak", league="LCK") + game("g2", a="A", b="B")
    df = load(tmp_path, rows, aliases)
    rep = report(df, aliases)
    assert rep["unknown_teams"] == []
    assert rep["other_teams"] == 2
    assert {"Zed", "Yak"} <= set(df["teamname"])


def test_unknown_team_in_international_league_is_reported(tmp_path, aliases):
    rows = game("g1", a="Zed", b="A", league="LCK") + game(
        "g2", a="Yak", b="B", league="WLDs"
    )
    rep = report(load(tmp_path, rows, aliases), aliases)
    assert rep["unknown_teams"] == ["Yak"]
    assert rep["other_teams"] == 1  # Zed


def test_required_team_missing_from_data_is_reported(tmp_path, aliases):
    df = load(tmp_path, game("g1", league="LCK"), aliases)
    assert report(df, aliases, required=["Ghost"])["unknown_teams"] == ["Ghost"]


def test_required_team_that_is_canonical_is_fine(tmp_path, aliases):
    df = load(tmp_path, game("g1", league="LCK"), aliases)
    assert report(df, aliases, required=["A"])["unknown_teams"] == []


def test_report_reads_international_leagues_from_config(tmp_path, aliases):
    df = load(tmp_path, game("g1", a="Zed", league="WLDs"), aliases)
    rep = ingest_report(
        df, aliases, required_teams=[]
    )  # leagues from config/ingest.yaml
    assert rep["unknown_teams"] == ["Zed"]
