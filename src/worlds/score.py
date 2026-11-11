"""Score the frozen Worlds 2026 pre-quarterfinal prediction against what happened.

Reads the saved prediction (never writes it), re-derives the series and game probabilities
from its cutoff ratings, and compares them with the hand-entered results. Ratings are never
rebuilt from post-cutoff games; the only post-cutoff rows read are the WLDs knockout games
used to cross-check the results file.
"""

import argparse
import hashlib
import itertools
import json
import math
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from numpy.polynomial.hermite_e import hermegauss

from worlds.backtest import _blue_red, bootstrap_diff, brier, log_loss, per_game_loss
from worlds.bracket import game1_blue_prob
from worlds.elo import expected_score
from worlds.series import bo5_rofs_win_prob
from worlds.simulate import (
    CONFIG_FILES,
    GAMES_PATH,
    _sha256,
    load_config,
    run_simulation,
)

SCORE_CONFIG_PATH = Path("config/score.yaml")
IDS = ("QF1", "QF2", "QF3", "QF4", "SF1", "SF2", "F")
ROUND_OF = {"QF": "quarterfinals", "SF": "semifinals", "F": "final"}
STAGES = ("semifinal", "final", "title")
BASELINES = ("half", "blue_only")


class IncompleteResults(ValueError):
    pass


@dataclass(frozen=True)
class Series:
    id: str
    round_name: str  # key in config rofs_game1
    a: str | None  # None until the teams are decided
    b: str | None
    winner: str | None
    score: tuple[int, int] | None  # (winner's games, loser's games)
    games: tuple[tuple[str, str], ...]  # (blue team, winner) in play order
    start: pd.Timestamp | None  # naive UTC


def _utc(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t


# ---------- saved prediction ----------


def load_prediction(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def _git_bytes(*args: str) -> bytes:
    try:
        return subprocess.run(["git", *args], capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        raise ValueError(f"git {' '.join(args)} failed: {e.stderr.decode().strip()}")


def tag_config(tag: str, pred: dict) -> dict:
    """The config the prediction was made with, read from the tag's own files. Raises
    unless the tag points at the recorded commit and the files hash to the recorded
    config_sha256."""
    commit = _git_bytes("rev-list", "-n1", tag).decode().strip()
    if commit != pred["meta"]["commit"]:
        raise ValueError(
            f"tag {tag} is at commit {commit}, the prediction records {pred['meta']['commit']}"
        )
    blobs = {p: _git_bytes("show", f"{tag}:{p}") for p in CONFIG_FILES}
    got = hashlib.sha256(b"".join(blobs[p] for p in CONFIG_FILES)).hexdigest()
    if got != pred["meta"]["config_sha256"]:
        raise ValueError(
            f"config at {tag} hashes to {got}, the prediction records {pred['meta']['config_sha256']}"
        )
    return load_config(lambda p: blobs[p].decode())


def check_prediction(pred: dict, cfg: dict, rng: np.random.Generator) -> None:
    """Re-run the saved simulation (saved strengths, H, q, sigma, n_runs; rng seeded by the
    caller with the saved seed) and raise unless it reproduces the saved odds."""
    m = pred["meta"]
    table = run_simulation(
        pred["strengths"], m["H"], m["q"], cfg, m["n_runs"], rng, m["sigma"]
    ).round(4)
    bad = [
        f"{team} {stage}: saved {v}, recomputed {table.loc[team, stage]}"
        for team, row in pred["odds"].items()
        for stage, v in row.items()
        if team not in table.index or abs(table.loc[team, stage] - v) > 1e-9
    ]
    if bad or set(pred["odds"]) != set(table.index):
        raise ValueError(
            "the saved prediction does not reproduce from the tagged config: "
            + "; ".join(bad or ["different teams"])
        )


# ---------- probabilities ----------


def noise_avg(f: Callable[[float], float], sigma: float, nodes: int) -> float:
    """E[f(d)] for d ~ N(0, sigma*sqrt(2)): the difference of two teams' N(0, sigma) noise.
    Gauss-Hermite quadrature, so it needs no random numbers."""
    x, w = hermegauss(nodes)
    d = sigma * math.sqrt(2) * x
    return float(np.sum(w * np.array([f(v) for v in d])) / math.sqrt(2 * math.pi))


def series_prob(
    a: str,
    b: str,
    round_name: str,
    strengths: dict[str, float],
    h: float,
    q: float,
    cfg: dict,
    sigma: float,
    nodes: int,
) -> float:
    """P(a wins the Bo5 | a meets b), the sim's series model averaged over the rating noise."""
    g1 = game1_blue_prob(round_name, a, b, q, cfg)
    return noise_avg(
        lambda d: bo5_rofs_win_prob(strengths[a] + d, strengths[b], h, q, g1),
        sigma,
        nodes,
    )


def game_prob(
    blue: str,
    red: str,
    strengths: dict[str, float],
    h: float,
    sigma: float,
    nodes: int,
) -> float:
    """P(blue wins a game) from the cutoff ratings, averaged over the rating noise."""
    return noise_avg(
        lambda d: expected_score(strengths[blue] + d, strengths[red], h), sigma, nodes
    )


def bracket_odds(
    pf: Callable[[str, str, str], float], qfs: list, sfs: list
) -> dict[str, dict[str, float]]:
    """Exact P(SF), P(final), P(title) by enumerating the 2^7 outcomes. pf(round, a, b) is
    P(a beats b) in that round's series."""
    out = {t: dict.fromkeys(STAGES, 0.0) for pair in qfs for t in pair}
    for qbits in itertools.product((0, 1), repeat=4):
        pq, w = 1.0, []
        for (a, b), bit in zip(qfs, qbits):
            p = pf("quarterfinals", a, b)
            pq *= p if bit == 0 else 1 - p
            w.append(b if bit else a)
        for sbits in itertools.product((0, 1), repeat=2):
            ps, f = pq, []
            for (i, j), bit in zip(sfs, sbits):
                p = pf("semifinals", w[i], w[j])
                ps *= p if bit == 0 else 1 - p
                f.append(w[j] if bit else w[i])
            for fbit in (0, 1):
                p = pf("final", *f)
                pr = ps * (p if fbit == 0 else 1 - p)
                for t in w:
                    out[t]["semifinal"] += pr
                for t in f:
                    out[t]["final"] += pr
                out[f[fbit]]["title"] += pr
    return out


# ---------- results file ----------


def parse_results(doc: dict, cfg: dict, partial: bool = False) -> list[Series]:
    """Validate the hand-entered results. QF pairs come from the config; SF and final pairs
    from the winners entered. Raises IncompleteResults if a series has no winner and
    partial is False."""
    raw = doc["series"]
    unknown = set(raw) - set(IDS)
    if unknown:
        raise ValueError(f"unknown series in results file: {sorted(unknown)}")
    qfs, sfs = cfg["knockout"]["quarterfinals"], cfg["knockout"]["semifinals"]
    done: dict[str, Series] = {}

    def build(sid: str, pair) -> Series:
        r = raw.get(sid) or {}
        round_name = ROUND_OF[sid.rstrip("0123456789")]
        start = _utc(r["start_utc"]) if r.get("start_utc") else None
        winner, games = r.get("winner"), r.get("games") or []
        if pair is None:
            if winner or games:
                raise ValueError(
                    f"{sid}: has results but its teams are not decided yet"
                )
            return Series(sid, round_name, None, None, None, None, (), start)
        a, b = pair
        tally = dict.fromkeys(pair, 0)
        played = []
        for n, g in enumerate(games, 1):
            if g["blue"] not in pair or g["winner"] not in pair:
                raise ValueError(f"{sid} game {n}: blue/winner not in {list(pair)}")
            if max(tally.values()) == 3:
                raise ValueError(f"{sid} game {n}: played after the series was decided")
            tally[g["winner"]] += 1
            played.append((g["blue"], g["winner"]))
        if winner is None:
            return Series(sid, round_name, a, b, None, None, tuple(played), start)
        if winner not in pair:
            raise ValueError(f"{sid}: winner {winner!r} is not in {list(pair)}")
        loser = b if winner == a else a
        want = (3, tally[loser])
        if tally[winner] != 3 or tally[loser] > 2:
            raise ValueError(
                f"{sid}: games give {tally}, not a finished Bo5 won by {winner}"
            )
        if tuple(r.get("score") or ()) != want:
            raise ValueError(
                f"{sid}: score {r.get('score')} does not match the games {want}"
            )
        return Series(sid, round_name, a, b, winner, want, tuple(played), start)

    def pair_of(ids):
        ws = [done[i].winner for i in ids]
        return tuple(ws) if all(ws) else None

    for i, pair in enumerate(qfs, 1):
        done[f"QF{i}"] = build(f"QF{i}", tuple(pair))
    for k, (i, j) in enumerate(sfs, 1):
        done[f"SF{k}"] = build(f"SF{k}", pair_of([f"QF{i + 1}", f"QF{j + 1}"]))
    done["F"] = build("F", pair_of(["SF1", "SF2"]))
    out = [done[i] for i in IDS]
    missing = [s.id for s in out if s.winner is None]
    if missing and not partial:
        raise IncompleteResults(
            f"results incomplete, no winner for {missing}; pass --partial to score what exists"
        )
    return out


def check_against_csv(
    series: list[Series], games: pd.DataFrame, cutoff: pd.Timestamp
) -> dict[str, str]:
    """Compare each finished series with the post-cutoff WLDs games in the Oracle's Elixir
    data (matching on blue team and winner, in date order). Raises on any disagreement."""
    g = games[
        (games["league"] == "WLDs")
        & (games["date"] >= cutoff)
        & (games["date"].dt.year == cutoff.year)
    ]
    table = _blue_red(g).sort_values(["date", "gameid"]) if len(g) else None
    status = {}
    for s in series:
        if s.winner is None:
            continue
        csv = []
        if table is not None:
            m = table[
                ((table["blue"] == s.a) & (table["red"] == s.b))
                | ((table["blue"] == s.b) & (table["red"] == s.a))
            ]
            csv = [
                (r.blue, r.blue if r.result == 1 else r.red)
                for r in m.itertuples(index=False)
            ]
        if not csv:
            status[s.id] = "unverified (not in the CSV)"
        elif len(csv) > len(s.games) or csv != list(s.games[: len(csv)]):
            raise ValueError(
                f"{s.id}: the CSV games {csv} disagree with the results file {list(s.games)}"
            )
        elif len(csv) < len(s.games):
            status[s.id] = f"partly verified ({len(csv)} of {len(s.games)} games)"
        else:
            status[s.id] = "verified"
    return status


# ---------- odds snapshots ----------


def margin_free(odds: dict[str, float]) -> dict[str, float]:
    """Decimal odds -> implied probabilities normalised to sum to 1."""
    if any(o <= 1 for o in odds.values()):
        raise ValueError(f"decimal odds must be above 1: {odds}")
    imp = {t: 1 / o for t, o in odds.items()}
    total = sum(imp.values())
    return {t: v / total for t, v in imp.items()}


def load_odds(odds_dir: Path, info: dict[str, tuple]) -> dict[str, dict]:
    """Per series, the latest snapshot strictly before the series' start. info is
    {series id: (team a, team b, start)}. Snapshots at or after the start are rejected
    (reported, not used). Returns {} when there is no snapshot file."""
    odds_dir = Path(odds_dir)
    files = sorted(odds_dir.glob("worlds_2026_*.yaml")) if odds_dir.is_dir() else []
    by_series: dict[str, list[dict]] = {}
    for f in files:
        d = yaml.safe_load(f.read_text())
        sid = d["series"]
        if sid not in info:
            raise ValueError(f"{f}: series {sid} has no known teams and start_utc")
        a, b, _ = info[sid]
        if set(d["odds"]) != {a, b}:
            raise ValueError(
                f"{f}: odds are for {sorted(d['odds'])}, the series is {a} v {b}"
            )
        margin_free(d["odds"])  # validates the odds
        by_series.setdefault(sid, []).append(
            {
                "file": f.name,
                "bookmaker": d["bookmaker"],
                "timestamp_utc": _utc(d["timestamp_utc"]),
                "odds": d["odds"],
            }
        )
    out = {}
    for sid, snaps in by_series.items():
        start = info[sid][2]
        before = [s for s in snaps if s["timestamp_utc"] < start]
        rejected = [s for s in snaps if s["timestamp_utc"] >= start]
        if before:
            chosen = max(before, key=lambda s: s["timestamp_utc"])
            out[sid] = {
                "chosen": chosen,
                "rejected": rejected,
                "p": margin_free(chosen["odds"]),
            }
    return out


# ---------- scoring ----------


def round_scores(
    odds: dict[str, dict[str, float]], outcomes: dict[str, set[str]]
) -> dict[str, dict]:
    """Log loss and Brier of P(stage) over the 8 teams, for each stage in outcomes
    ({stage: teams that reached it})."""
    teams = sorted(odds)
    out = {}
    for stage, reached in outcomes.items():
        p = [odds[t][stage] for t in teams]
        y = [int(t in reached) for t in teams]
        out[stage] = {"n": len(teams), "log_loss": log_loss(p, y), "brier": brier(p, y)}
    return out


def _outcomes(series: list[Series]) -> dict[str, set[str]]:
    w = {s.id: s.winner for s in series}
    out = {}
    if all(w[f"QF{i}"] for i in range(1, 5)):
        out["semifinal"] = {w[f"QF{i}"] for i in range(1, 5)}
    if w["SF1"] and w["SF2"]:
        out["final"] = {w["SF1"], w["SF2"]}
    if w["F"]:
        out["title"] = {w["F"]}
    return out


def _lb(p, y) -> dict:
    return {"log_loss": log_loss(p, y), "brier": brier(p, y)}


def score_all(
    pred: dict,
    cfg: dict,
    series: list[Series],
    odds: dict[str, dict],
    rng: np.random.Generator,
    nodes: int,
    n_boot: int,
) -> dict:
    """All levels (series, round, game, odds) for the finished series. Ratings are the
    prediction's own cutoff ratings, frozen; nothing is updated during the knockout."""
    m, strengths = pred["meta"], pred["strengths"]
    h, q, sigma = m["H"], m["q"], m["sigma"]
    done = [s for s in series if s.winner is not None]

    def blue_only(round_name, a, b):
        return bo5_rofs_win_prob(
            0.0, 0.0, h, q, game1_blue_prob(round_name, a, b, q, cfg)
        )

    rows = []
    for s in done:
        p = series_prob(s.a, s.b, s.round_name, strengths, h, q, cfg, sigma, nodes)
        rows.append(
            {
                "series": s.id,
                "a": s.a,
                "b": s.b,
                "winner": s.winner,
                "score": list(s.score),
                "p_a_model": p,
                "p_a_blue_only": blue_only(s.round_name, s.a, s.b),
                "a_won": int(s.winner == s.a),
            }
        )
    y = [r["a_won"] for r in rows]
    series_scores = {
        "model": _lb([r["p_a_model"] for r in rows], y),
        "half": _lb([0.5] * len(rows), y),
        "blue_only": _lb([r["p_a_blue_only"] for r in rows], y),
    }

    outcomes = _outcomes(series)
    qfs, sfs = cfg["knockout"]["quarterfinals"], cfg["knockout"]["semifinals"]
    base_odds = {
        "half": bracket_odds(lambda r, a, b: 0.5, qfs, sfs),
        "blue_only": bracket_odds(blue_only, qfs, sfs),
    }
    model_r = round_scores(pred["odds"], outcomes)
    base_r = {k: round_scores(v, outcomes) for k, v in base_odds.items()}
    rounds = {
        st: {
            "n": model_r[st]["n"],
            "model": model_r[st],
            **{k: base_r[k][st] for k in BASELINES},
        }
        for st in model_r
    }

    r_blue = expected_score(0.0, 0.0, h)  # the blue win rate H was fitted on
    grows, yg = [], []
    for s in done:
        for n, (blue, win) in enumerate(s.games, 1):
            red = s.b if blue == s.a else s.a
            grows.append(
                {
                    "series": s.id,
                    "game": n,
                    "blue": blue,
                    "red": red,
                    "p_blue_model": game_prob(blue, red, strengths, h, sigma, nodes),
                    "blue_won": int(win == blue),
                }
            )
            yg.append(int(win == blue))
    pg = {
        "model": [r["p_blue_model"] for r in grows],
        "half": [0.5] * len(grows),
        "blue_only": [r_blue] * len(grows),
    }
    zero = np.zeros(len(grows))
    games = {"rows": grows}
    for k, p in pg.items():
        _, lo, hi = bootstrap_diff(per_game_loss(p, yg), zero, n_boot, rng)
        games[k] = {**_lb(p, yg), "ci95": [lo, hi]}
    d, lo, hi = bootstrap_diff(
        per_game_loss(pg["model"], yg), per_game_loss(pg["blue_only"], yg), n_boot, rng
    )
    games["model_minus_blue_only"] = {"mean": d, "ci95": [lo, hi]}

    by_id = {r["series"]: r for r in rows}
    orows = []
    for sid, o in odds.items():
        if sid not in by_id:
            continue  # snapshot for a series that has not finished
        r = by_id[sid]
        orows.append(
            {
                "series": sid,
                "bookmaker": o["chosen"]["bookmaker"],
                "timestamp_utc": str(o["chosen"]["timestamp_utc"]),
                "rejected_after_start": [x["file"] for x in o["rejected"]],
                "p_a_bookmaker": o["p"][r["a"]],
                "p_a_model": r["p_a_model"],
                "a_won": r["a_won"],
            }
        )
    yo = [r["a_won"] for r in orows]
    odds_out: dict = {"n": len(orows), "rows": orows}
    if orows:
        odds_out |= {
            "bookmaker_log_loss": log_loss([r["p_a_bookmaker"] for r in orows], yo),
            "model_log_loss": log_loss([r["p_a_model"] for r in orows], yo),
            "half_log_loss": log_loss([0.5] * len(orows), yo),
        }
    else:
        odds_out["note"] = "skipped: no odds snapshot before a finished series' start"

    return {
        "partial": len(done) < len(IDS),
        "n": {
            "series": len(done),
            "games": len(grows),
            "odds_series": len(orows),
            "round_items": sum(v["n"] for v in rounds.values()),
        },
        "series": rows,
        "series_scores": series_scores,
        "rounds": rounds,
        "games": games,
        "odds": odds_out,
    }


# ---------- output ----------


def render_md(doc: dict) -> str:
    n, m = doc["n"], doc["meta"]

    def f(x: float) -> str:
        return f"{x:.3f}"

    def ci(c: list) -> str:
        return f"[{c[0]:.3f}, {c[1]:.3f}]"

    lines = [
        "# Worlds 2026 pre-quarterfinal prediction: score"
        + (" (PARTIAL)" if doc["partial"] else ""),
        "",
        (
            f"**n = {n['series']} series, {n['games']} games, {n['round_items']} round items "
            f"({n['odds_series']} series with odds).** This is far too little to say anything about model quality."
        ),
        "",
        f"- tag: `{m['tag']}` (commit `{m['tag_commit']}`)",
        f"- prediction: `{m['prediction_file']}`, config_sha256 `{m['prediction']['config_sha256']}`, data_sha256 `{m['prediction']['data_sha256']}`",
        f"- results file: `{m['results_file']}`, sha256 `{m['results_sha256']}`",
        (
            "- ratings frozen at the cutoff; probabilities averaged over the rating noise "
            f"(sigma {m['prediction']['sigma']}, {m['quadrature_nodes']}-node Gauss-Hermite), conditional on the matchup happening."
        ),
        "- for SF and final matchups this ignores that the sim's advancing teams tended to have positive noise.",
        "- baselines: half = 0.5 everywhere (round level: every series 0.5); blue_only = equal strengths, only the blue bonus H.",
        f"- results vs the CSV: {m['csv_check']}",
        "",
        "## Series (P that the first-listed team wins)",
        "",
        "| series | A | B | P(A) model | P(A) blue-only | winner | score |",
        "|---|---|---|---|---|---|---|",
        *(
            f"| {r['series']} | {r['a']} | {r['b']} | {f(r['p_a_model'])} | {f(r['p_a_blue_only'])} | {r['winner']} | {r['score'][0]}-{r['score'][1]} |"
            for r in doc["series"]
        ),
        "",
        "| | log loss | Brier |",
        "|---|---|---|",
        *(
            f"| {k} | {f(v['log_loss'])} | {f(v['brier'])} |"
            for k, v in doc["series_scores"].items()
        ),
        "",
        "## Rounds (8 teams each)",
        "",
        "| round | model LL | half LL | blue-only LL | model Brier | half Brier | blue-only Brier |",
        "|---|---|---|---|---|---|---|",
        *(
            f"| {st} | {f(v['model']['log_loss'])} | {f(v['half']['log_loss'])} | {f(v['blue_only']['log_loss'])} | {f(v['model']['brier'])} | {f(v['half']['brier'])} | {f(v['blue_only']['brier'])} |"
            for st, v in doc["rounds"].items()
        ),
        "",
        f"## Games (n = {n['games']}, log loss with bootstrap 95% CI)",
        "",
        "| | log loss | 95% CI | Brier |",
        "|---|---|---|---|",
        *(
            f"| {k} | {f(doc['games'][k]['log_loss'])} | {ci(doc['games'][k]['ci95'])} | {f(doc['games'][k]['brier'])} |"
            for k in ("model", "half", "blue_only")
        ),
        "",
        f"model minus blue-only: {doc['games']['model_minus_blue_only']['mean']:.3f} {ci(doc['games']['model_minus_blue_only']['ci95'])} (negative = model better)",
        "",
        "## Odds",
        "",
    ]
    o = doc["odds"]
    if o["n"]:
        lines += [
            (
                f"n = {o['n']} series. Margin removed by normalising. Snapshot = latest before the series start; "
                "later series' odds know earlier results, the frozen model does not."
            ),
            "",
            f"log loss: bookmaker {f(o['bookmaker_log_loss'])}, model {f(o['model_log_loss'])}, half {f(o['half_log_loss'])}",
            "",
            "| series | bookmaker | snapshot (UTC) | P(A) bookmaker | P(A) model | A won |",
            "|---|---|---|---|---|---|",
            *(
                f"| {r['series']} | {r['bookmaker']} | {r['timestamp_utc']} | {f(r['p_a_bookmaker'])} | {f(r['p_a_model'])} | {r['a_won']} |"
                for r in o["rows"]
            ),
        ]
        rej = [x for r in o["rows"] for x in r["rejected_after_start"]]
        if rej:
            lines += ["", f"rejected (at or after the series start): {rej}"]
    else:
        lines.append(o["note"])
    return "\n".join(lines) + "\n"


def write_score(
    doc: dict, md: str, out_dir: Path, stem: str, partial: bool
) -> list[Path]:
    """Write <stem>[_partial][_vN].{json,md} with the first N whose files do not exist;
    open(mode="x") so an existing file is never touched."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = stem + ("_partial" if partial else "")
    for v in itertools.count(1):
        name = base if v == 1 else f"{base}_v{v}"
        paths = [out_dir / f"{name}.json", out_dir / f"{name}.md"]
        if not any(p.exists() for p in paths):
            break
    for p, text in zip(paths, (json.dumps(doc, indent=2, default=str), md)):
        with p.open("x") as fh:
            fh.write(text)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--partial", action="store_true", help="score the finished series only"
    )
    args = ap.parse_args()

    sc = yaml.safe_load(SCORE_CONFIG_PATH.read_text())
    pred_path, results_path = Path(sc["prediction"]), Path(sc["results"])
    pred = load_prediction(pred_path)
    cfg = tag_config(sc["tag"], pred)
    check_prediction(pred, cfg, np.random.default_rng(pred["meta"]["seed"]))

    try:
        series = parse_results(
            yaml.safe_load(results_path.read_text()), cfg, args.partial
        )
    except IncompleteResults as e:
        sys.exit(str(e))
    cutoff = pd.Timestamp(cfg["prediction_cutoff"])
    if GAMES_PATH.exists():
        csv_check = check_against_csv(series, pd.read_parquet(GAMES_PATH), cutoff)
    else:
        csv_check = {s.id: "unverified (no games.parquet)" for s in series if s.winner}
    info = {s.id: (s.a, s.b, s.start) for s in series if s.a and s.start}
    odds = load_odds(Path(sc["odds_dir"]), info)

    rng = np.random.default_rng(cfg["random_seed"])
    doc = score_all(
        pred, cfg, series, odds, rng, sc["quadrature_nodes"], cfg["bootstrap_samples"]
    )
    doc["meta"] = {
        "tag": sc["tag"],
        "tag_commit": pred["meta"]["commit"],
        "prediction_file": str(pred_path),
        "prediction": {
            k: pred["meta"][k]
            for k in (
                "commit",
                "config_sha256",
                "data_sha256",
                "seed",
                "n_runs",
                "H",
                "q",
                "sigma",
            )
        },
        "results_file": str(results_path),
        "results_sha256": _sha256(results_path),
        "csv_check": csv_check,
        "quadrature_nodes": sc["quadrature_nodes"],
        "bootstrap_samples": cfg["bootstrap_samples"],
        "partial": doc["partial"],
    }
    for p in write_score(
        doc, render_md(doc), Path(sc["out_dir"]), sc["out_stem"], doc["partial"]
    ):
        print(f"Wrote {p}")
    print(f"n = {doc['n']}: far too small to judge the model")


if __name__ == "__main__":
    main()
