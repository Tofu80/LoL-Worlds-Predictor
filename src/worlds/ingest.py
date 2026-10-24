import sys
from pathlib import Path

import pandas as pd
import yaml

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
ALIASES_PATH = Path("config/team_aliases.yaml")

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


def load_games(path: Path, aliases_path: Path = ALIASES_PATH) -> pd.DataFrame:
    """Load one Oracle's Elixir CSV; return validated team rows (position == 'team').

    Columns: gameid, date, league, teamname, side, result, patch, datacompleteness.
    The raw file is only read. Team names are mapped through the aliases in
    aliases_path (the only place names are rewritten). No row is dropped:
    rows with datacompleteness != 'complete' are kept (see ingest_report) and
    unknown team names are kept (see ingest_report).

    Dates are parsed as ISO 8601 and stay timezone-naive, as in the source, so a
    cutoff_date such as pd.Timestamp("2024-10-01") means 00:00:00 on that day at
    the same naive dtype, and a game at or after that instant is not "before" it.

    Raises ValueError, listing gameids, for a missing/unparseable date, or a
    gameid whose two rows don't have the same date, opposite sides, different
    teams (after aliasing) and exactly one win.
    """
    raw = pd.read_csv(
        path,
        usecols=[*COLUMNS, "position"],
        dtype={"gameid": str, "patch": str},
    )
    df = raw[raw["position"] == "team"][COLUMNS].reset_index(drop=True)
    no_team_rows = set(raw["gameid"].dropna()) - set(df["gameid"].dropna())
    if no_team_rows:
        raise ValueError(_fail("gameid with no team rows", no_team_rows))
    df["date"] = pd.to_datetime(df["date"], format="ISO8601", errors="coerce")
    aliases = yaml.safe_load(Path(aliases_path).read_text())["aliases"] or {}
    df["teamname"] = df["teamname"].replace(aliases)
    _validate(df)
    df["result"] = df["result"].astype(int)
    return df


def ingest_report(games: pd.DataFrame, aliases_path: Path = ALIASES_PATH) -> dict:
    """Report what load_games kept but the model should know about.

    unknown_teams: sorted team names not in canonical (after aliasing).
    incomplete_games_by_league: {league: games with datacompleteness != 'complete'}.
    """
    cfg = yaml.safe_load(Path(aliases_path).read_text())
    canonical = set(cfg["canonical"] or [])
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
    return {
        "unknown_teams": sorted(set(games["teamname"].dropna()) - canonical),
        "incomplete_games_by_league": {k: int(v) for k, v in by_league.items()},
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
    games = pd.concat([load_games(p) for p in paths], ignore_index=True)
    _validate(games)  # catches a gameid that appears in two files
    report = ingest_report(games)
    print(f"{len(games) // 2} games from {len(paths)} file(s)")
    print(f"Incomplete games by league: {report['incomplete_games_by_league']}")
    if report["unknown_teams"]:
        sys.exit(
            f"Unknown teams, add them to {ALIASES_PATH} (nothing written): "
            f"{report['unknown_teams']}"
        )
    print(f"Wrote {write_processed(games, 'games')}")


if __name__ == "__main__":
    main()
