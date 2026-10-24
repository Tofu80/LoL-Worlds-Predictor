import sys
from pathlib import Path

import pandas as pd
import yaml

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
ALIASES_PATH = Path("config/team_aliases.yaml")
EXCLUSIONS_PATH = Path("config/data_exclusions.yaml")
INGEST_CONFIG_PATH = Path("config/ingest.yaml")
FORMAT_GLOB = "config/worlds_*.yaml"

COLUMNS = [
    "gameid",
    "date",
    "league",
    "teamname",
    "side",
    "result",
    "patch",
    "datacompleteness",
]


def _read_alias_config(path: Path) -> dict:
    """Return {"canonical", "aliases", "league_aliases"}; ValueError naming path if malformed.

    league_aliases is optional: [{from, to, leagues}] renames `from` to `to` only on rows
    whose league is in `leagues` (for a name shared by two different teams).
    """
    cfg = yaml.safe_load(Path(path).read_text())
    if not isinstance(cfg, dict):
        msg = f"{path}: expected a mapping with 'canonical' and 'aliases'"
        raise ValueError(msg)  # noqa: TRY004 (bad config is a ValueError by design)
    for key in ("canonical", "aliases"):
        if key not in cfg:
            raise ValueError(f"{path}: missing '{key}' section")
    canonical = cfg["canonical"] or []
    aliases = cfg["aliases"] or {}
    if not isinstance(canonical, list):
        raise ValueError(f"{path}: 'canonical' must be a list")  # noqa: TRY004
    if not isinstance(aliases, dict):
        msg = f"{path}: 'aliases' must be a mapping of name -> canonical name"
        raise ValueError(msg)  # noqa: TRY004
    names = [*canonical, *aliases, *aliases.values()]
    bad = [n for n in names if not isinstance(n, str) or not n]
    if bad:
        raise ValueError(f"{path}: team names must be non-empty strings, got {bad}")
    rules = cfg.get("league_aliases") or []
    if not isinstance(rules, list):
        raise ValueError(f"{path}: 'league_aliases' must be a list")  # noqa: TRY004
    for rule in rules:
        ok = isinstance(rule, dict) and all(
            isinstance(rule.get(k), str) and rule[k] for k in ("from", "to")
        )
        leagues = rule.get("leagues") if isinstance(rule, dict) else None
        ok = ok and rule["from"] != rule["to"] and isinstance(leagues, list)
        ok = ok and bool(leagues) and all(isinstance(x, str) and x for x in leagues)
        if not ok:
            msg = f"{path}: each league alias needs from, to (different) and leagues"
            raise ValueError(msg)
    return {"canonical": canonical, "aliases": aliases, "league_aliases": rules}


def _read_exclusions(path: Path) -> dict[str, str]:
    """Return {gameid: reason}; raise ValueError naming path if malformed."""
    cfg = yaml.safe_load(Path(path).read_text())
    if not isinstance(cfg, dict) or not isinstance(cfg.get("exclusions"), list):
        msg = f"{path}: expected a mapping with an 'exclusions' list"
        raise ValueError(msg)  # noqa: TRY004 (bad config is a ValueError by design)
    out: dict[str, str] = {}
    for entry in cfg["exclusions"]:
        gid = entry.get("gameid") if isinstance(entry, dict) else None
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if not all(isinstance(v, str) and v for v in (gid, reason)):
            msg = f"{path}: each exclusion needs a non-empty string gameid and reason"
            raise ValueError(msg)
        if gid in out:
            raise ValueError(f"{path}: duplicate gameid {gid!r}")
        out[gid] = reason
    return out


def _read_excluded_leagues(path: Path) -> list[str]:
    """Return config/ingest.yaml `excluded_leagues` ([] if absent); ValueError if malformed."""
    cfg = yaml.safe_load(Path(path).read_text()) or {}
    leagues = cfg.get("excluded_leagues") or []
    if not isinstance(leagues, list) or not all(
        isinstance(x, str) and x for x in leagues
    ):
        raise ValueError(f"{path}: 'excluded_leagues' must be a list of league names")
    return leagues


def _fail(problem: str, gameids) -> str:
    ids = sorted(map(str, gameids))
    return f"{problem}: {len(ids)} gameid(s), first {ids[:10]}"


def _validate(df: pd.DataFrame) -> None:
    """Raise ValueError if any game is not exactly one clean two-team result.

    Never drops rows: either every game passes or the load stops.
    """
    problems = []
    if not pd.api.types.is_datetime64_dtype(df["date"]):
        raise ValueError("dates must be one timezone-naive column, as in the source")
    if df["gameid"].isna().any():
        problems.append(f"{int(df['gameid'].isna().sum())} row(s) with a blank gameid")
    nat = df.loc[df["date"].isna(), "gameid"].unique()
    if len(nat):
        problems.append(_fail("missing or unparseable date", nat))

    g = df.groupby("gameid")
    per_game = pd.DataFrame(
        {
            "rows": g.size(),
            "dates": g["date"].nunique(),
            "teams": g["teamname"].nunique(),
            "blue": g["side"].apply(lambda s: (s == "Blue").sum()),
            "red": g["side"].apply(lambda s: (s == "Red").sum()),
            "wins": g["result"].apply(lambda s: (s == 1).sum()),
            "losses": g["result"].apply(lambda s: (s == 0).sum()),
        }
    )
    checks = {
        "gameid without exactly two team rows": per_game["rows"] != 2,
        "the two rows have different dates": per_game["dates"] > 1,
        "sides are not one Blue and one Red": (per_game["blue"] != 1)
        | (per_game["red"] != 1),
        "both rows are the same (or a missing) team": per_game["teams"] != 2,
        "not exactly one win and one loss": (per_game["wins"] != 1)
        | (per_game["losses"] != 1),
    }
    for problem, bad in checks.items():
        if bad.any():
            problems.append(_fail(problem, per_game.index[bad]))
    if problems:
        raise ValueError("; ".join(problems))


def load_games(
    path: Path,
    aliases_path: Path = ALIASES_PATH,
    exclusions_path: Path = EXCLUSIONS_PATH,
    ingest_config_path: Path = INGEST_CONFIG_PATH,
) -> pd.DataFrame:
    """Load one Oracle's Elixir CSV; return validated team rows (position == 'team').

    Columns: gameid, date, league, teamname, side, result, patch, datacompleteness.
    The raw file is only read. Team names are mapped through the aliases in
    aliases_path (the only place names are rewritten; league_aliases there first rename
    a name that two teams share, by league). The only games dropped are
    those in a league listed under `excluded_leagues` in ingest_config_path (counted in
    df.attrs["excluded_by_league"]) and the gameids listed in exclusions_path that
    still fail validation (df.attrs["excluded_gameids"]; see ingest_report). A listed
    gameid that now validates raises ValueError: remove it from the list. Rows with
    datacompleteness != 'complete' and unknown team names are kept (see
    ingest_report).

    Dates are parsed as ISO 8601 and stay timezone-naive. Oracle's Elixir dates are
    UTC (checked against the 2023 Seoul, 2024 London and 2025 Chengdu finals start
    times). Games can run past midnight UTC (Worlds 2026 is in the US), so compare
    by full timestamp, never by calendar date: a cutoff_date may be a full
    timestamp, pd.Timestamp("2024-10-01") means 00:00:00 UTC that day, and a game at
    or after that instant is not "before" it.

    Raises ValueError, listing gameids, for a missing/unparseable date, or a
    gameid whose two rows don't have the same date, opposite sides, different
    teams (after aliasing) and exactly one win.
    """
    raw = pd.read_csv(
        path,
        usecols=[*COLUMNS, "position"],
        dtype={"gameid": str, "patch": str},
    )
    skip = _read_excluded_leagues(ingest_config_path)
    in_skipped = raw["league"].isin(skip)
    skipped_teams = raw[in_skipped & (raw["position"] == "team")]
    excluded_by_league = {  # team rows / 2, so a blank gameid is still counted
        k: int(v) // 2 for k, v in skipped_teams.groupby("league").size().items()
    }
    raw = raw[~in_skipped]
    excluded = _read_exclusions(exclusions_path)
    listed = set(raw["gameid"]) & set(excluded)
    df = raw[raw["position"] == "team"][COLUMNS].reset_index(drop=True)
    no_team_rows = set(raw["gameid"].dropna()) - set(df["gameid"].dropna()) - listed
    if no_team_rows:
        raise ValueError(_fail("gameid with no team rows", no_team_rows))
    df["date"] = pd.to_datetime(df["date"], format="ISO8601", errors="coerce")
    alias_cfg = _read_alias_config(aliases_path)
    for rule in alias_cfg["league_aliases"]:  # before plain aliases
        rows = df["league"].isin(rule["leagues"]) & (df["teamname"] == rule["from"])
        df.loc[rows, "teamname"] = rule["to"]
    df["teamname"] = df["teamname"].replace(alias_cfg["aliases"])
    is_listed = df["gameid"].isin(listed)
    for gid in sorted(listed & set(df["gameid"])):
        try:
            _validate(df[df["gameid"] == gid])
        except ValueError:
            continue  # still broken: dropped below
        msg = (
            f"{gid}: exclusion no longer needed, remove it from {exclusions_path.name}"
        )
        raise ValueError(msg)
    df = df[~is_listed].reset_index(drop=True)
    _validate(df)
    df["result"] = df["result"].astype(int)
    df.attrs["excluded_gameids"] = sorted(listed)  # list: parquet-safe
    df.attrs["excluded_by_league"] = excluded_by_league
    return df


def _worlds_teams() -> list[str]:
    """Union of `teams` over config/worlds_<year>.yaml."""
    teams: set[str] = set()
    for path in sorted(Path().glob(FORMAT_GLOB)):
        teams |= set(yaml.safe_load(path.read_text()).get("teams") or [])
    return sorted(teams)


def ingest_report(
    games: pd.DataFrame,
    aliases_path: Path = ALIASES_PATH,
    international_leagues: list[str] | None = None,
    required_teams: list[str] | None = None,
    exclusions_path: Path = EXCLUSIONS_PATH,
    excluded_gameids: set[str] | None = None,
    excluded_leagues: dict[str, int] | None = None,
) -> dict:
    """Report what load_games kept but the model should know about.

    unknown_teams: sorted names (after aliasing) not in canonical that play in an
        international league, or are in required_teams (even with no games).
    other_teams: count of other names not in canonical; they pass through as teams.
    incomplete_games_by_league: {league: games with datacompleteness != 'complete'}.
    excluded_games: {gameid: reason} for listed games actually dropped.
    exclusions_not_found: listed gameids not in the file(s) loaded.
    excluded_leagues: {league: games dropped} for leagues in `excluded_leagues` config.
    excluded_leagues_not_found: configured leagues with no games dropped in any file
        (e.g. Oracle's Elixir renamed the league, so the filter matches nothing).

    international_leagues defaults to config/ingest.yaml, required_teams to the
    `teams` of config/worlds_*.yaml, excluded_gameids to games.attrs (pass the union
    across files when games was concatenated); excluded_leagues likewise (summed).
    """
    canonical = set(_read_alias_config(aliases_path)["canonical"])
    if international_leagues is None:
        cfg = yaml.safe_load(INGEST_CONFIG_PATH.read_text())
        international_leagues = cfg["international_leagues"]
    if required_teams is None:
        required_teams = _worlds_teams()
    if excluded_gameids is None:
        excluded_gameids = set(games.attrs.get("excluded_gameids", []))
    if excluded_leagues is None:
        excluded_leagues = games.attrs.get("excluded_by_league", {})
    listed = _read_exclusions(exclusions_path)
    # A game is incomplete if either of its rows is; league may be blank.
    flag = games["datacompleteness"].ne("complete")
    per_game = (
        games.assign(incomplete=flag)
        .groupby("gameid")
        .agg(incomplete=("incomplete", "any"), league=("league", "first"))
    )
    by_league = (
        per_game[per_game["incomplete"]]["league"].fillna("(blank)").value_counts()
    )
    names = set(games["teamname"].dropna())
    intl_names = set(
        games.loc[games["league"].isin(international_leagues), "teamname"].dropna()
    )
    must_know = intl_names | set(required_teams)
    return {
        "unknown_teams": sorted(must_know - canonical),
        "other_teams": len(names - canonical - must_know),
        "incomplete_games_by_league": {k: int(v) for k, v in by_league.items()},
        "excluded_games": {
            g: listed[g] for g in sorted(excluded_gameids & set(listed))
        },
        "exclusions_not_found": sorted(set(listed) - set(excluded_gameids)),
        "excluded_leagues": dict(excluded_leagues),
        "excluded_leagues_not_found": sorted(
            set(_read_excluded_leagues(INGEST_CONFIG_PATH)) - set(excluded_leagues)
        ),
    }


def write_processed(df: pd.DataFrame, name: str, out_dir: Path = PROCESSED_DIR) -> Path:
    """Write df to <out_dir>/<name>.parquet (default data/processed/); return the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path


def main() -> None:
    paths = sorted(RAW_DIR.glob("*.csv"))
    if not paths:
        sys.exit(f"No CSVs found in {RAW_DIR}/ (download Oracle's Elixir files there)")
    frames = [load_games(p) for p in paths]
    excluded = {g for f in frames for g in f.attrs["excluded_gameids"]}
    by_league: dict[str, int] = {}
    for f in frames:
        for k, v in f.attrs["excluded_by_league"].items():
            by_league[k] = by_league.get(k, 0) + v
    games = pd.concat(frames, ignore_index=True)
    _validate(games)  # catches a gameid that appears in two files
    report = ingest_report(games, excluded_gameids=excluded, excluded_leagues=by_league)
    for p, f in zip(paths, frames, strict=True):
        dropped = f.attrs["excluded_by_league"]
        note = f" (dropped by league: {dropped})" if dropped else ""
        print(f"{p.name}: {len(f) // 2} games{note}")
    print(f"{len(games) // 2} games from {len(paths)} file(s)")
    print(f"Excluded games: {report['excluded_games']}")
    print(f"Excluded games by league: {report['excluded_leagues']}")
    print(f"Excluded leagues not found: {report['excluded_leagues_not_found']}")
    print(f"Exclusions not found in files: {report['exclusions_not_found']}")
    print(f"Incomplete games by league: {report['incomplete_games_by_league']}")
    print(f"Other (non-canonical, pass-through) teams: {report['other_teams']}")
    if report["unknown_teams"]:
        sys.exit(
            f"Unknown teams, add them to {ALIASES_PATH} (nothing written): "
            f"{report['unknown_teams']}"
        )
    print(f"Wrote {write_processed(games, 'games')}")


if __name__ == "__main__":
    main()
