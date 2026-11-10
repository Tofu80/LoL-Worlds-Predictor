import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from numpy.random import Generator

from worlds import elo
from worlds.backtest import _blue_red
from worlds.bracket import STAGES, simulate_bracket
from worlds.series import rofs_q

GAMES_PATH = Path("data/processed/games.parquet")
CONFIG_FILES = [
    Path("config/elo.yaml"),
    Path("config/backtest.yaml"),
    Path("config/ingest.yaml"),
    Path("config/worlds_2026.yaml"),
    Path("config/team_aliases.yaml"),
]
RAW_2026 = Path("data/raw/2026_LoL_esports_match_data_from_OraclesElixir.csv")
OUT_DIRS = [Path("data/processed/predictions"), Path("results")]
OUT_NAME = "worlds_2026_preQF"


def load_config() -> dict:
    """elo.yaml + worlds_2026.yaml + ingest.yaml's international_leagues, one flat dict."""
    cfg = {
        **yaml.safe_load(Path("config/elo.yaml").read_text()),
        **yaml.safe_load(Path("config/worlds_2026.yaml").read_text()),
    }
    cfg["international_leagues"] = yaml.safe_load(
        Path("config/ingest.yaml").read_text()
    )["international_leagues"]
    return cfg


def _before_cutoff(games: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    return games[games["date"] < pd.Timestamp(cfg["prediction_cutoff"])]


def _swiss_records(swiss: pd.DataFrame, gap_hours: float) -> dict[str, list[int]]:
    """Swiss (wins, losses) per team. A series = consecutive games of the same two
    teams less than gap_hours apart; the team with more game wins takes it."""
    records: dict[str, list[int]] = {}
    series: list[dict] = []  # open series per pair, in date order
    last: dict[frozenset, dict] = {}
    for g in swiss.sort_values(["date", "gameid"]).itertuples(index=False):
        pair = frozenset((g.blue, g.red))
        s = last.get(pair)
        if s is None or (g.date - s["end"]) >= pd.Timedelta(hours=gap_hours):
            s = {"end": g.date, "wins": {g.blue: 0, g.red: 0}}
            series.append(s)
            last[pair] = s
        s["end"] = g.date
        s["wins"][g.blue if g.result == 1 else g.red] += 1
    for s in series:
        (a, wa), (b, wb) = s["wins"].items()
        if wa == wb:
            raise ValueError(f"Swiss series between {a} and {b} is tied {wa}-{wb}")
        win, lose = (a, b) if wa > wb else (b, a)
        records.setdefault(win, [0, 0])[0] += 1
        records.setdefault(lose, [0, 0])[1] += 1
    return records


def validate_pre_cutoff(games: pd.DataFrame, cfg: dict) -> dict:
    """Raise ValueError unless the data before prediction_cutoff is exactly a play-in
    plus a finished Swiss stage with the configured records. Returns a summary.

    Checks: (1) every WLDs game in [start_date, cutoff) is play-in (before swiss_start)
    or Swiss (on/after swiss_start, both teams among the 16); WLDs games before
    start_date are regional qualifiers, counted but not checked; (2) Swiss records
    recomputed from the games match swiss_results and everyone else is out on 3 losses;
    (3) no game in any league falls between the last Swiss game and the cutoff.
    """
    cutoff = pd.Timestamp(cfg["prediction_cutoff"])
    start, swiss_start = (
        pd.Timestamp(cfg["start_date"]),
        pd.Timestamp(cfg["swiss_start"]),
    )
    games = _before_cutoff(games, cfg)
    wlds = games[(games["league"] == "WLDs") & (games["date"].dt.year == cutoff.year)]
    table = _blue_red(wlds) if len(wlds) else pd.DataFrame(columns=["date"])
    n_qualifier = int((table["date"] < start).sum())
    swiss_teams = set(cfg["teams"])
    in_window = table[table["date"] >= start]
    swiss = in_window[in_window["date"] >= swiss_start]
    bad = swiss[~(swiss["blue"].isin(swiss_teams) & swiss["red"].isin(swiss_teams))]
    if len(bad):
        raise ValueError(
            f"WLDs games on/after swiss_start that are not play-in or Swiss: {list(bad['gameid'][:10])}"
        )
    if swiss.empty:
        raise ValueError("no Swiss games before the cutoff")

    records = _swiss_records(swiss, cfg["rofs_series_gap_hours"])
    expected = {t: list(r) for t, r in cfg["swiss_results"].items()}
    problems = []
    for t in sorted(swiss_teams):
        got = records.get(t, [0, 0])
        if t in expected:
            if got != expected[t]:
                problems.append(f"{t}: got {got}, expected {expected[t]}")
        elif not (
            got[1] == cfg["swiss"]["loss_target"]
            and got[0] < cfg["swiss"]["win_target"]
        ):
            problems.append(f"{t}: got {got}, expected eliminated (x-3)")
    if problems:
        raise ValueError(
            "Swiss records do not match swiss_results: " + "; ".join(problems)
        )

    last_swiss = swiss["date"].max()
    gap = games[(games["date"] > last_swiss) & (games["date"] < cutoff)]
    if len(gap):
        raise ValueError(
            f"{gap['gameid'].nunique()} game(s) between the last Swiss game {last_swiss} "
            f"and the cutoff {cutoff}: {sorted(gap['gameid'].unique())[:5]}"
        )
    return {
        "n_swiss_games": len(swiss),
        "n_playin_games": int(len(in_window) - len(swiss)),
        "n_qualifier_wlds": n_qualifier,
        "last_swiss_game": last_swiss,
        "records": {t: records.get(t, [0, 0]) for t in sorted(swiss_teams)},
    }


def rating_state(games: pd.DataFrame, cfg: dict) -> elo.EloState:
    """Ratings as the backtest builds them: replay games before start_date (H fixed from
    them), then add every game in [start_date, prediction_cutoff) at full K."""
    start = pd.Timestamp(cfg["start_date"])
    games = _before_cutoff(games, cfg)
    state = elo.replay(games, start, cfg)
    window = games[games["date"] >= start]
    table = _blue_red(window).sort_values(["date", "gameid"])
    for g in table.itertuples(index=False):
        state.update(g.blue, g.red, g.league, bool(g.result == 1), cfg["k_factor"])
    return state


def run_simulation(
    strengths: dict[str, float],
    h: float,
    q: float,
    config: dict,
    n_runs: int,
    rng: Generator,
    sigma: float,
) -> pd.DataFrame:
    """Monte Carlo of the knockout bracket. Each run adds N(0, sigma) to every team's
    strength. Returns {team: P(semifinal), P(final), P(title)}, sorted by title."""
    teams = sorted(strengths)
    reach = {s: dict.fromkeys(teams, 0) for s in STAGES[1:]}
    for _ in range(n_runs):
        noise = rng.normal(0.0, sigma, size=len(teams))
        noisy = {t: strengths[t] + e for t, e in zip(teams, noise)}
        for t, stage in simulate_bracket(noisy, h, q, config, rng).items():
            for s in STAGES[1 : STAGES.index(stage) + 1]:
                reach[s][t] += 1
    out = pd.DataFrame(reach) / n_runs
    out.columns = ["semifinal", "final", "title"]
    return out.sort_values("title", ascending=False)


def predict(games: pd.DataFrame, cfg: dict, n_runs: int, rng: Generator) -> dict:
    """The pre-quarterfinal prediction from games before prediction_cutoff only."""
    games = _before_cutoff(games, cfg)  # nothing later is read past this line
    summary = validate_pre_cutoff(games, cfg)
    state = rating_state(games, cfg)
    q, n_q = rofs_q(
        games,
        pd.Timestamp(cfg["prediction_cutoff"]),
        cfg["rofs_q_leagues"],
        cfg["rofs_series_gap_hours"],
    )
    strengths = {t: state.strength(t) for t in cfg["swiss_results"]}
    table = run_simulation(strengths, state.h, q, cfg, n_runs, rng, cfg["rating_noise"])
    return {
        "table": table,
        "strengths": strengths,
        "h": state.h,
        "q": q,
        "n_q": n_q,
        "sigma": cfg["rating_noise"],
        "n_runs": n_runs,
        "validation": summary,
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def write_outputs(
    result: dict, cfg: dict, games: pd.DataFrame, seed: int
) -> list[Path]:
    """Write the .json and .md (with provenance) to every OUT_DIR; returns the paths."""
    cutoff = pd.Timestamp(cfg["prediction_cutoff"])
    config_hash = hashlib.sha256(
        b"".join(p.read_bytes() for p in CONFIG_FILES)
    ).hexdigest()
    meta = {
        "commit": _git("rev-parse", "HEAD"),
        "dirty_worktree": bool(_git("status", "--porcelain")),
        "config_sha256": config_hash,
        "prediction_cutoff_utc": cutoff.isoformat(),
        "last_game_used_utc": str(_before_cutoff(games, cfg)["date"].max()),
        "csv_snapshot": {
            "file": RAW_2026.name,
            "sha256": _sha256(RAW_2026),
            "modified": pd.Timestamp(RAW_2026.stat().st_mtime, unit="s").isoformat(),
        },
        "H": result["h"],
        "q": result["q"],
        "n_q": result["n_q"],
        "sigma": result["sigma"],
        "n_runs": result["n_runs"],
        "seed": seed,
        "model": {
            k: cfg[k]
            for k in (
                "k_factor",
                "decay_half_life_days",
                "side_advantage",
                "league_offsets",
                "k_league",
            )
        },
    }
    table = result["table"].round(4)
    doc = {
        "meta": meta,
        "strengths": result["strengths"],
        "odds": table.to_dict("index"),
    }
    lines = [
        "# Worlds 2026 pre-quarterfinal prediction",
        "",
        "Retroactive: data strictly before the cutoff only; no knockout result used.",
        "",
        *(f"- {k}: `{v}`" for k, v in meta.items() if k != "model"),
        f"- model: `{meta['model']}`",
        "",
        "| team | strength | P(SF) | P(final) | P(title) |",
        "|---|---|---|---|---|",
        *(
            f"| {t} | {result['strengths'][t]:.1f} | {r.semifinal:.3f} | {r.final:.3f} | {r.title:.3f} |"
            for t, r in table.iterrows()
        ),
        "",
    ]
    paths = []
    for d in OUT_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{OUT_NAME}.json").write_text(json.dumps(doc, indent=2, default=str))
        (d / f"{OUT_NAME}.md").write_text("\n".join(lines))
        paths += [d / f"{OUT_NAME}.json", d / f"{OUT_NAME}.md"]
    return paths


def main() -> None:
    if not GAMES_PATH.exists():
        sys.exit(f"{GAMES_PATH} not found: run python -m worlds.ingest first")
    cfg = load_config()
    games = pd.read_parquet(GAMES_PATH)
    games = _before_cutoff(games, cfg)  # drop everything from the cutoff on, unread
    rng = np.random.default_rng(cfg["random_seed"])
    result = predict(games, cfg, cfg["simulation_count"], rng)
    v = result["validation"]
    print(
        f"Validated: {v['n_playin_games']} play-in + {v['n_swiss_games']} Swiss games, "
        f"{v['n_qualifier_wlds']} WLDs qualifier games before start_date; last Swiss game {v['last_swiss_game']}"
    )
    print(
        f"H = {result['h']:.1f}, q = {result['q']:.3f} (n = {result['n_q']}), sigma = {result['sigma']}"
    )
    print(result["table"].round(4).to_string())
    for p in write_outputs(result, cfg, games, cfg["random_seed"]):
        print(f"Wrote {p}")


if __name__ == "__main__":
    main()
