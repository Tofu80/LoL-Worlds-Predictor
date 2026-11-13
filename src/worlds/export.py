"""Export team-level model outputs as JSON for the static site (site/data/).

Every probability carries a provenance:
  frozen        the tagged pre-quarterfinal prediction (never re-run); a series probability
                for a pair the saved odds do not cover is computed from the frozen inputs
                by score.series_prob (derivation says so)
  walk_forward  backtest and 2026 play-in/Swiss: computed afterwards, each game from games
                dated before it only
  sensitivity   the frozen run with one assumption changed (Overview only)

2026 games from prediction_cutoff on are dropped right after loading and never read; the
2026 knockout comes from the saved score output, or is pending. Raw Oracle's Elixir rows,
player columns and bookmaker snapshots never reach the output.
"""

import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from worlds import backtest as bt
from worlds import elo, score
from worlds import simulate as sim
from worlds.series import series_win_prob

EXPORT_CONFIG_PATH = Path("config/export.yaml")
SCORE_CONFIG_PATH = Path("config/score.yaml")
PROVENANCE = ("frozen", "walk_forward", "sensitivity", "replay")
DERIVATION = ("saved", "computed_from_frozen_inputs", "walk_forward_replay")
# k_league is chosen on these Worlds (backtest.compare's grid): their matches are in-sample for it.
K_LEAGUE_FIT_YEARS = (2023, 2024)


def legends(exp: dict, pred: dict, generated: datetime) -> tuple[dict, dict]:
    """Provenance and derivation wording, with every date taken from the files."""
    cutoff = pd.Timestamp(pred["meta"]["prediction_cutoff_utc"]).date()
    committed = pd.Timestamp(exp["frozen_committed_utc"]).date()
    legend = {
        "frozen": (
            f"Frozen: computed from games before {cutoff} only, ratings fixed at that cutoff, "
            f"committed {committed} (code at tag {exp['frozen_tag']}, output in "
            f"{exp['frozen_output_commit']}) after the quarterfinals had started, and never re-run."
        ),
        "walk_forward": (
            "Walk-forward: computed afterwards. Each game is predicted from games dated before "
            "it, with results added game by game; H and the decay weights are fixed at the "
            "start of each Worlds, and k_league was chosen on the 2023-24 results. Not a "
            "live prediction."
        ),
        "replay": (
            "Rating reconstructed with this tournament's settings (H and decay fixed at the "
            "start date). Shown for context. Not a prediction made at the time."
        ),
        "sensitivity": (
            "Sensitivity: the frozen run repeated after the fact with one assumption changed "
            "(who holds the side choice in quarterfinal game 1). A what-if."
        ),
    }
    derivation = {
        "saved": f"Saved in the frozen prediction file on {committed}.",
        "computed_from_frozen_inputs": (
            f"Computed at export time ({generated.date()}) from the frozen inputs (same "
            f"ratings, H, q and sigma) by score.py; not saved on {committed}."
        ),
        "walk_forward_replay": "Replayed after the event, using only earlier games.",
    }
    return legend, derivation


VARIANTS = {
    "current": "Original Elo (no side bonus, no league offsets)",
    "+H": "Elo + blue-side bonus",
    "+H+league": "Elo + blue-side bonus + league offsets (the model)",
    "blue-only": "Blue-side bonus only (equal teams)",
    "0.5": "Coin flip (0.5 every game)",
}
KO_ROUNDS = ["quarterfinal"] * 4 + ["semifinal"] * 2 + ["final"]
STAGE_ORDER = ["play-in", "swiss", "quarterfinal", "semifinal", "final", "champion"]
HISTORY_COLUMNS = [
    "date",
    "opponent",
    "strength_before",
    "strength_after",
    "offset_after",
    "gameid",
    "segment",
    "provenance",
]


def load_export_config() -> dict:
    cfg = yaml.safe_load(EXPORT_CONFIG_PATH.read_text())
    cfg["stages"] = {
        y: {k: pd.Timestamp(v) for k, v in s.items()} for y, s in cfg["stages"].items()
    }
    cfg["frozen_committed_utc"] = pd.Timestamp(cfg["frozen_committed_utc"])
    return cfg


# ---------- series ----------


def build_series(table: pd.DataFrame, gap_hours: float) -> list[dict]:
    """Group games (gameid, date, blue, red, result; result 1 = blue won) into series:
    consecutive games of the same two teams less than gap_hours apart. A pair may meet in
    several series. Returns dicts with a, b (blue/red of game 1), games, wins, start."""
    out, open_ = [], {}
    for g in table.sort_values(["date", "gameid"]).itertuples(index=False):
        pair = frozenset((g.blue, g.red))
        s = open_.get(pair)
        if s is None or (g.date - s["end"]) >= pd.Timedelta(hours=gap_hours):
            s = {
                "a": g.blue,
                "b": g.red,
                "games": [],
                "wins": {g.blue: 0, g.red: 0},
                "start": g.date,
            }
            out.append(s)
            open_[pair] = s
        s["end"] = g.date
        s["games"].append(g)
        s["wins"][g.blue if g.result == 1 else g.red] += 1
    return out


def series_format(s: dict) -> str:
    """bo1 / bo3 / bo5 from the winner's game wins (1 / 2 / 3); raises on anything else."""
    wa, wb = s["wins"][s["a"]], s["wins"][s["b"]]
    win, lose = max(wa, wb), min(wa, wb)
    fmt = {1: "bo1", 2: "bo3", 3: "bo5"}.get(win)
    if wa == wb or fmt is None or lose >= win or (fmt == "bo1" and lose):
        raise ValueError(
            f"series {s['a']} v {s['b']} {s['start']}: odd score {wa}-{wb}"
        )
    return fmt


def winner_of(s: dict) -> str:
    return max(s["wins"], key=s["wins"].get)


def label_stages(series: list[dict], swiss_start, knockout_start=None) -> None:
    """Set s["stage"]: play-in before swiss_start, swiss until knockout_start, then the
    knockout in time order as 4 quarterfinals, 2 semifinals and a final (raises otherwise).
    knockout_start None = no knockout yet: everything from swiss_start on is Swiss."""
    ko = []
    for s in series:
        if s["start"] < swiss_start:
            s["stage"] = "play-in"
        elif knockout_start is None or s["start"] < knockout_start:
            s["stage"] = "swiss"
        else:
            ko.append(s)
    if knockout_start is not None:
        if len(ko) != len(KO_ROUNDS):
            raise ValueError(f"{len(ko)} knockout series, expected {len(KO_ROUNDS)}")
        for s, name in zip(ko, KO_ROUNDS):
            s["stage"] = name


def swiss_records(series: list[dict]) -> dict[str, list[int]]:
    rec: dict[str, list[int]] = {}
    for s in series:
        if s["stage"] != "swiss":
            continue
        w = s["result"]["winner"]
        for t in (s["a"], s["b"]):
            rec.setdefault(t, [0, 0])[0 if t == w else 1] += 1
    return rec


def check_swiss(rec: dict[str, list[int]], year: int, total: int = 16) -> None:
    """16 teams, and each one ends on exactly 3 wins or exactly 3 losses (8 and 8)."""
    adv = [t for t, (w, l) in rec.items() if w == 3 and l < 3]
    out = [t for t, (w, l) in rec.items() if l == 3 and w < 3]
    if len(rec) != total or len(adv) != total // 2 or len(out) != total // 2:
        raise ValueError(
            f"{year}: Swiss records do not end 8 at 3 wins and 8 at 3 losses "
            f"({len(rec)} teams, {len(adv)} advance, {len(out)} out): check the stage dates"
        )


def check_knockout(series: list[dict], rec: dict, year: int) -> None:
    adv = {t for t, (w, _) in rec.items() if w == 3}
    qf = {t for s in series if s["stage"] == "quarterfinal" for t in (s["a"], s["b"])}
    if qf != adv:
        raise ValueError(f"{year}: quarterfinalists are not the 8 Swiss qualifiers")


# ---------- walk-forward probabilities ----------


def neutral_series_p(sa: float, sb: float, h: float, fmt: str) -> float:
    """P(A wins) with the side effect averaged: constant per-game p = mean of A on blue and
    A on red, from ratings before game 1, through the Bo3/Bo5 formulas."""
    p = 0.5 * (elo.expected_score(sa, sb, h) + elo.expected_score(sa, sb, -h))
    return series_win_prob(p, fmt)


def _ll(p: float, won: int) -> float:
    return float(bt.per_game_loss([p], [won])[0])


def walk_forward_matches(
    preds: pd.DataFrame, history: pd.DataFrame, h: float, gap_hours: float
) -> list[dict]:
    """Series of one Worlds with walk-forward probabilities. preds: backtest predictions
    (gameid, date, blue, red, p_blue, result); history: that run's rating snapshots, whose
    'before' columns are exactly what predicted each game. Stage is not set here."""
    before = history.set_index(["gameid", "team"])
    out = []
    for s in build_series(preds, gap_hours):
        fmt = series_format(s)
        g1 = s["games"][0]
        strength = {
            t: float(
                before.loc[(g1.gameid, t), "rating_before"]
                + before.loc[(g1.gameid, t), "offset_before"]
            )
            for t in (s["a"], s["b"])
        }
        # The snapshots must reproduce the probability the backtest made for game 1; a
        # same-timestamp game updating ratings first would break this.
        again = elo.expected_score(strength[s["a"]], strength[s["b"]], h)
        if abs(again - g1.p_blue) > 1e-12:
            raise ValueError(
                f"{g1.gameid}: ratings before game 1 give {again}, backtest predicted {g1.p_blue}"
            )
        win = winner_of(s)
        # A = the blue team of game 1; a Bo1's probability is that game's own.
        p_a = (
            float(g1.p_blue)
            if fmt == "bo1"
            else neutral_series_p(strength[s["a"]], strength[s["b"]], h, fmt)
        )
        a_won = int(win == s["a"])
        loser = s["b"] if win == s["a"] else s["a"]
        out.append(
            {
                "a": s["a"],
                "b": s["b"],
                "format": fmt,
                "start": s["start"],
                "provenance": "walk_forward",
                "derivation": "walk_forward_replay",
                "p_a": p_a,
                "assumptions": {
                    "h": h,
                    "side": "each game uses the side actually played (blue gets +H)",
                    "series_model": (
                        "this game's own probability"
                        if fmt == "bo1"
                        else "constant per-game p, side-neutral, from ratings before game 1"
                    ),
                    "strength_a": strength[s["a"]],
                    "strength_b": strength[s["b"]],
                },
                "result": {
                    "status": "final",
                    "winner": win,
                    "score": [s["wins"][win], s["wins"][loser]],
                },
                "log_loss": _ll(p_a, a_won),
                "games": [
                    {
                        "gameid": g.gameid,
                        "n": n,
                        "date": g.date,
                        "blue": g.blue,
                        "red": g.red,
                        "p_blue": float(g.p_blue),
                        "blue_won": int(g.result),
                        "log_loss": _ll(float(g.p_blue), int(g.result)),
                        "provenance": "walk_forward",
                    }
                    for n, g in enumerate(s["games"], 1)
                ],
            }
        )
    return out


# ---------- frozen 2026 ----------


def pick_score_file(glob_pattern: str) -> Path | None:
    """Newest complete score output, else newest partial, else None."""
    pat = Path(glob_pattern)
    files = sorted(pat.parent.glob(pat.name)) if pat.parent.is_dir() else []

    def version(p: Path) -> int:
        m = re.search(r"_v(\d+)$", p.stem)
        return int(m.group(1)) if m else 1

    docs = [(p, json.loads(p.read_text())) for p in files]
    for want_partial in (False, True):
        pick = [p for p, d in docs if bool(d.get("partial")) == want_partial]
        if pick:
            return max(pick, key=version)
    return None


def knockout_matches(
    pred: dict,
    cfg_tag: dict,
    nodes: int,
    doc: dict | None,
    starts: dict[str, pd.Timestamp | None],
    committed: pd.Timestamp,
) -> list[dict]:
    """The seven 2026 knockout series: frozen probabilities, results from the score output
    (pending when absent). Never simulates: series probabilities come from
    score.series_prob on the saved strengths, H, q and sigma."""
    m, strengths = pred["meta"], pred["strengths"]
    h, q, sigma = m["H"], m["q"], m["sigma"]
    names = {"QF": "quarterfinal", "SF": "semifinal", "F": "final"}
    fin = {r["series"]: r for r in (doc or {}).get("series", [])}
    games: dict[str, list] = defaultdict(list)
    for r in (doc or {}).get("games", {}).get("rows", []):
        games[r["series"]].append(r)
    qfs = cfg_tag["knockout"]["quarterfinals"]
    out = []
    for sid in score.IDS:
        kind = sid.rstrip("0123456789")
        rnd = score.ROUND_OF[kind]
        r = fin.get(sid)
        if kind == "QF":
            a, b = qfs[int(sid[2:]) - 1]
        else:
            a, b = (r["a"], r["b"]) if r else (None, None)
        start = starts.get(sid)
        entry = {
            "id": f"2026-{sid}",
            "year": 2026,
            "stage": names[kind],
            "format": "bo5",
            "a": a,
            "b": b,
            "start": start,
            "played_before_commit": None if start is None else bool(start < committed),
            "provenance": "frozen",
            "result": {"status": "pending"},
        }
        if a is None:
            entry |= {"p_a": None, "derivation": None}
        else:
            p = score.series_prob(a, b, rnd, strengths, h, q, cfg_tag, sigma, nodes)
            entry |= {
                "p_a": p,
                "derivation": "computed_from_frozen_inputs",
                "assumptions": {
                    "h": h,
                    "q": q,
                    "sigma": sigma,
                    "side": (
                        f"right of first selection: game 1 holder per {cfg_tag['rofs_game1'][rnd]}, "
                        "later games the previous loser; the holder is blue with probability q"
                    ),
                    "series_model": (
                        "exact Bo5 recursion over sides, averaged over N(0, sigma) rating "
                        "noise (Gauss-Hermite), ratings frozen at the cutoff"
                    ),
                    "strength_a": strengths[a],
                    "strength_b": strengths[b],
                },
            }
        if r:
            if start is None:
                raise ValueError(
                    f"{sid} has a result but no start_utc in the results file"
                )
            if abs(entry["p_a"] - r["p_a_model"]) > 1e-9:
                raise ValueError(
                    f"{sid}: recomputed p {entry['p_a']} differs from the score file's "
                    f"{r['p_a_model']} (stale score file, or different quadrature nodes)"
                )
            entry["result"] = {
                "status": "final",
                "winner": r["winner"],
                "score": r["score"],
            }
            entry["log_loss"] = _ll(r["p_a_model"], r["a_won"])
            entry["games"] = [
                {
                    "n": g["game"],
                    "blue": g["blue"],
                    "red": g["red"],
                    "p_blue": g["p_blue_model"],
                    "blue_won": g["blue_won"],
                    "log_loss": _ll(g["p_blue_model"], g["blue_won"]),
                    "provenance": "frozen",
                    "derivation": "computed_from_frozen_inputs",
                }
                for g in games.get(sid, [])
            ]
        out.append(entry)
    return out


# ---------- teams ----------


def team_history(
    hist: dict[int, pd.DataFrame],
    seg_end: dict[int, pd.Timestamp],
    starts: dict[int, pd.Timestamp],
    scored: set,
) -> tuple[dict[str, list], dict[str, tuple]]:
    """One point per game per team across the per-Worlds segments. Segment Y = the rating
    history of Worlds Y's run (replay up to its start, then in-tournament) for games dated
    after Worlds Y-1's last scored game up to Worlds Y's last scored game: exactly the
    ratings the model had going into that Worlds. Returns ({team: points}, {team: (league
    key, offset) after its last point}). A point dated before its Worlds' start is a
    "replay" (rating rebuilt with that tournament's H and decay, not a prediction made at
    the time); from the start on it is "walk_forward"."""
    points: dict[str, list] = defaultdict(list)
    latest: dict[str, tuple] = {}
    prev = None
    for y in sorted(hist):
        h = hist[y]
        sel = h[h["date"] <= seg_end[y]]
        if prev is not None:
            sel = sel[sel["date"] > prev]
        prev = seg_end[y]
        for r in sel.sort_values("date", kind="stable").itertuples(index=False):
            points[r.team].append(
                [
                    iso(r.date),
                    r.opponent,
                    r.rating_before + r.offset_before,
                    r.rating_after + r.offset_after,
                    r.offset_after,
                    r.gameid if r.gameid in scored else None,
                    y,
                    "replay" if r.date < starts[y] else "walk_forward",
                ]
            )
            latest[r.team] = (r.league_after, r.offset_after)
    return points, latest


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.replace("Ø", "O").replace("ø", "o"))
    s = re.sub(r"[^a-z0-9]+", "-", s.encode("ascii", "ignore").decode().lower())
    return s.strip("-")


def iso(t) -> str | None:
    return None if t is None else pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M")


def stage_reached(matches: list[dict], team: str) -> str | None:
    best = -1
    for m in matches:
        if team not in (m["a"], m["b"]):
            continue
        best = max(best, STAGE_ORDER.index(m["stage"]))
        if (
            m["stage"] == "final"
            and m["result"].get("status") == "final"
            and m["result"]["winner"] == team
        ):
            best = STAGE_ORDER.index("champion")
    return None if best < 0 else STAGE_ORDER[best]


# ---------- json ----------


def clean(x, nd: int | None = 4):
    """JSON-ready copy: Timestamps as ISO minutes, numpy scalars as Python, floats rounded
    to nd places (None = untouched); NaN/inf raise."""
    if isinstance(x, pd.Timestamp):
        return iso(x)
    if hasattr(x, "item") and not isinstance(x, (list, dict, str)):
        x = x.item()
    if isinstance(x, float):
        if not math.isfinite(x):
            raise ValueError("non-finite number in export")
        return x if nd is None else round(x, nd)
    if isinstance(x, dict):
        return {str(k): clean(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v, nd) for v in x]
    return x


def calibration_rows(table: pd.DataFrame) -> list[dict]:
    return [
        {
            "bin": r.bin,
            "n": int(r.n),
            "mean_pred": None if math.isnan(r.mean_pred) else float(r.mean_pred),
            "observed": None if math.isnan(r.observed) else float(r.observed),
        }
        for r in table.itertuples(index=False)
    ]


def model_json(c: dict, config: dict) -> dict:
    """Backtest vs baselines from backtest.compare()."""
    base = bt._pool(c["runs"]["current"])
    half_by_year = {
        y: bt.score(base[base["date"].dt.year == y].assign(p_blue=0.5))
        for y in bt.YEARS
    }
    per = {
        **{n: c["runs"][n] for n in ("current", "+H", "+H+league")},
        "blue-only": c["blue_only_by_year"],
        "0.5": half_by_year,
    }
    pooled = {**c["pooled"], "blue-only": c["blue_only"], "0.5": c["half"]}
    variants = {
        n: {
            "label": label,
            "provenance": "walk_forward",
            "per_year": {
                str(y): {"log_loss": r.log_loss, "brier": r.brier, "n": r.n_games}
                for y, r in per[n].items()
            },
            "pooled": {
                "log_loss": pooled[n].log_loss,
                "brier": pooled[n].brier,
                "n": pooled[n].n_games,
            },
        }
        for n, label in VARIANTS.items()
    }
    return {
        "provenance": "walk_forward",
        "variants": variants,
        "model": "+H+league",
        "bootstrap_vs_current": {
            n: {"mean": m, "lo": lo, "hi": hi}
            for n, (m, lo, hi) in c["bootstrap"].items()
        },
        "bootstrap_samples": config["bootstrap_samples"],
        "calibration": {
            n: calibration_rows(c["pooled"][n].calibration)
            for n in ("current", "+H+league")
        },
        "calibration_by_class": {
            n: {
                k: {
                    "n": int(v[0]),
                    "mean_pred": v[1],
                    "observed": v[2],
                    "log_loss": v[3],
                }
                for k, v in rows.items()
            }
            for n, rows in c["by_class"].items()
        },
        "k_league": {
            "grid_pooled_2023_24": {str(k): v for k, v in c["grid"].items()},
            "chosen": c["best_k"],
            "note": (
                "k_league was chosen on the 2023-24 games that the pooled figure also "
                "includes; 2025 is the only year not used to choose it."
            ),
        },
        "merge_bar": c["merge"],
        "config": {
            k: config[k]
            for k in (
                "k_factor",
                "initial_rating",
                "decay_half_life_days",
                "side_advantage_window_days",
                "k_league",
            )
        },
    }


def overview_json(
    pred: dict,
    sens: dict,
    swiss: dict[str, list[int]],
    cfg_tag: dict,
    doc: dict | None,
    doc_name: str | None,
    exp: dict,
) -> dict:
    """Straight from the saved files; nothing is simulated. Floats are not rounded, so the
    frozen numbers equal the tagged JSON exactly."""
    m = pred["meta"]
    teams = [
        {
            "team": t,
            "strength": pred["strengths"][t],
            "swiss_record": swiss.get(t),
            **odds,
            "provenance": "frozen",
            "derivation": "saved",
            "sensitivity": {**sens["teams"][t]["variant"], "provenance": "sensitivity"},
        }
        for t, odds in pred["odds"].items()
    ]
    if doc is None:
        sc = {"status": "pending"}
    else:
        sc = {
            "status": "partial" if doc["partial"] else "complete",
            "file": doc_name,
            "provenance": "frozen",
            "derivation": "computed_from_frozen_inputs",
            "n": doc["n"],
            "series_scores": doc["series_scores"],
            "rounds": doc["rounds"],
            "games": {k: v for k, v in doc["games"].items() if k != "rows"},
            "odds": {
                k: doc["odds"][k]
                for k in ("n", "bookmaker_log_loss", "model_log_loss", "half_log_loss")
                if k in doc["odds"]
            },
        }
    return {
        "year": 2026,
        "frozen": {
            "provenance": "frozen",
            "tag": exp["frozen_tag"],
            "commit": m["commit"],
            "committed_utc": iso(exp["frozen_committed_utc"]),
            "prediction_cutoff_utc": m["prediction_cutoff_utc"],
            "H": m["H"],
            "q": m["q"],
            "sigma": m["sigma"],
            "n_runs": m["n_runs"],
            "seed": m["seed"],
        },
        "teams": sorted(teams, key=lambda t: -t["title"]),
        "bracket": {
            "quarterfinals": [
                {"id": f"2026-QF{i}", "a": a, "b": b}
                for i, (a, b) in enumerate(cfg_tag["knockout"]["quarterfinals"], 1)
            ],
            "semifinals": cfg_tag["knockout"]["semifinals"],
        },
        "sensitivity": {
            "provenance": "sensitivity",
            "variant": sens["meta"]["variant"],
            "max_abs_title_change": sens["max_abs_title_change"],
            "qf_series": [
                {
                    "a": s["a"],
                    "b": s["b"],
                    "p_a_frozen": s["primary"],
                    "p_a": s["variant"],
                }
                for s in sens["qf_series"]
            ],
        },
        "score": sc,
    }


# ---------- build ----------


def integrity(games: pd.DataFrame, cfg26: dict, pred: dict) -> elo.EloState:
    """Raise unless the data and replay reproduce the frozen prediction's inputs; returns
    the replayed state."""
    if sim.games_sha256(games, cfg26) != pred["meta"]["data_sha256"]:
        raise ValueError(
            "games before the cutoff no longer hash to the frozen prediction's data_sha256: "
            "the walk-forward numbers would not match the frozen ones"
        )
    sim.validate_pre_cutoff(games, cfg26)
    state = sim.rating_state(games, cfg26)
    bad = {
        t: (state.strength(t), v)
        for t, v in pred["strengths"].items()
        if abs(state.strength(t) - v) > 1e-9
    }
    if bad:
        raise ValueError(f"replayed 2026 strengths differ from the frozen ones: {bad}")
    return state


def check_same_ratings(history: pd.DataFrame, state: elo.EloState, teams) -> None:
    """The exported 2026 history (backtest path) must end on the team ratings of the
    frozen path (simulate.rating_state), for every team given."""
    bad = {}
    for t in teams:
        last = history[history["team"] == t].iloc[-1]["rating_after"]
        if abs(last - state.team[t]) > 1e-9:
            bad[t] = (last, state.team[t])
    if bad:
        raise ValueError(f"exported 2026 history ends off the frozen ratings: {bad}")


def check_pinned(path: Path, sha256: str, what: str) -> None:
    """Raise unless the file's bytes are the ones pinned in config/export.yaml."""
    got = sim._sha256(Path(path))
    if got != sha256:
        raise ValueError(
            f"{what} {path} hashes to {got}, config/export.yaml pins {sha256}"
        )


def check_score_results(doc: dict, results_path: Path) -> None:
    """The score output must have been made from the results file now on disk."""
    got = sim._sha256(Path(results_path))
    if doc["meta"]["results_sha256"] != got:
        raise ValueError(
            f"score output used a results file with sha256 {doc['meta']['results_sha256']}, "
            f"{results_path} is now {got}: run worlds.score again"
        )


def build_all(
    games: pd.DataFrame,
    exp: dict,
    bcfg: dict,
    cfg26: dict,
    pred: dict,
    sens: dict,
    cfg_tag: dict,
    doc: dict | None,
    doc_name: str | None,
    starts: dict,
    nodes: int,
    meta_extra: dict | None = None,
) -> dict[str, object]:
    """{relative path under out_dir: JSON-able object}. games is cut at the 2026
    prediction_cutoff first, so no knockout row is ever read."""
    games = sim._before_cutoff(games, cfg26)
    state = integrity(games, cfg26, pred)

    k = pred["meta"]["model"]["k_league"]
    if not (
        bcfg["k_league"] == k and bcfg["rating_updates"] == cfg26["rating_updates"]
    ):
        raise ValueError("backtest config differs from the frozen prediction's model")
    c = bt.compare(games, bcfg, record=True)
    if c["best_k"] != k:
        raise ValueError(f"grid picks k_league={c['best_k']}, frozen model has {k}")
    model_cfg = {
        **bcfg,
        "side_advantage": "pre_cutoff_rate",
        "league_offsets": "on",
        "k_league": k,
    }
    start26 = pd.Timestamp(cfg26["start_date"])
    res26 = bt.backtest_worlds(
        2026,
        games,
        {**model_cfg, "tournaments": {2026: {"start_date": cfg26["start_date"]}}},
        start26,
        record=True,
    )
    results = {**c["runs"]["+H+league"], 2026: res26}

    matches, swiss_by_year = [], {}
    gap = exp["series_gap_hours"]
    for year, res in results.items():
        start = pd.Timestamp(
            bcfg["tournaments"][year]["start_date"] if year != 2026 else start26
        )
        h = elo.blue_advantage(games, start, bcfg["side_advantage_window_days"])
        ms = walk_forward_matches(res.predictions, res.history, h, gap)
        if year == 2026:
            label_stages(ms, pd.Timestamp(cfg26["swiss_start"]))
            rec = swiss_records(ms)
            want = {t: list(r) for t, r in cfg26["swiss_results"].items()}
            check_swiss(rec, year, cfg26["swiss"]["total_teams"])
            if any(rec[t] != r for t, r in want.items()):
                raise ValueError("2026 Swiss records differ from worlds_2026.yaml")
        else:
            st = exp["stages"][year]
            label_stages(ms, st["swiss_start"], st["knockout_start"])
            rec = swiss_records(ms)
            check_swiss(rec, year, cfg26["swiss"]["total_teams"])
            check_knockout(ms, rec, year)
        swiss_by_year[year] = rec
        for m in ms:
            m["assumptions"]["k_league_in_sample"] = year in K_LEAGUE_FIT_YEARS
        if year == 2026:
            check_same_ratings(res.history, state, cfg26["swiss_results"])
        for n, s in enumerate(ms, 1):
            s["id"], s["year"] = f"{year}-{n:03d}", year
        matches += ms
    matches += knockout_matches(
        pred, cfg_tag, nodes, doc, starts, exp["frozen_committed_utc"]
    )

    scored = {g["gameid"] for m in matches for g in m.get("games", []) if "gameid" in g}
    seg_end = {y: res.predictions["date"].max() for y, res in results.items()}
    starts = {
        y: pd.Timestamp(bcfg["tournaments"][y]["start_date"] if y != 2026 else start26)
        for y in results
    }
    points, latest = team_history(
        {y: r.history for y, r in results.items()}, seg_end, starts, scored
    )
    names = sorted({t for m in matches for t in (m["a"], m["b"]) if t})
    slugs = {t: slugify(t) for t in names}
    if len(set(slugs.values())) != len(slugs):
        raise ValueError("two team names give the same slug")

    odds26 = pred["odds"]
    files: dict[str, object] = {}
    index = []
    for t in names:
        mine = [m for m in matches if t in (m["a"], m["b"])]
        worlds = {}
        for y, res in results.items():
            ym = [m for m in mine if m["year"] == y]
            if not ym:
                continue
            first = res.history[
                (res.history["team"] == t) & res.history["scored"]
            ].iloc[0]
            worlds[str(y)] = {
                "league": first["league_before"],
                "league_offset": first["offset_before"],
                "rating": first["rating_before"],
                "strength": first["rating_before"] + first["offset_before"],
                "swiss_record": swiss_by_year[y].get(t),
                "stage_reached": stage_reached(ym, t),
                "provenance": "walk_forward",
            }
        league, offset = latest[t]
        team = {
            "name": t,
            "slug": slugs[t],
            "league": league,
            "league_offset": offset,
            "as_of": points[t][-1][
                0
            ],  # league and offset are as of the team's last game
            "worlds": worlds,
            "history": {
                "note": (
                    "Strength = team rating + league offset, one point per game. Each "
                    "segment is the rating the model had going into that Worlds. Points "
                    "before the start date are replay, from the start date on walk_forward; "
                    "each point carries its own provenance."
                ),
                "segment_starts": {str(y): iso(t) for y, t in starts.items()},
                "columns": HISTORY_COLUMNS,
                "points": points[t],
            },
            "matches": [m["id"] for m in mine],
        }
        obj = clean(team, 1)  # ratings to 1 decimal
        if t in odds26:  # saved 4-decimal odds, copied untouched
            obj["path_to_title"] = {
                **odds26[t],
                "provenance": "frozen",
                "derivation": "saved",
            }
        files[f"teams/{slugs[t]}.json"] = obj
        index.append(
            {
                "name": t,
                "slug": slugs[t],
                "league": league,
                "years": sorted(int(y) for y in worlds),
            }
        )
    files["teams/index.json"] = {
        "schema_version": exp["schema_version"],
        "teams": index,
    }
    nd = exp["decimals"]["probability"]
    files["matches.json"] = {
        "schema_version": exp["schema_version"],
        "matches": clean(matches, nd),
    }
    files["model.json"] = clean(model_json(c, bcfg), nd)
    files["overview_2026.json"] = clean(
        overview_json(pred, sens, swiss_by_year[2026], cfg_tag, doc, doc_name, exp),
        None,
    )
    generated = datetime.now(timezone.utc)
    legend, derivation_text = legends(exp, pred, generated)
    files["meta.json"] = {
        "schema_version": exp["schema_version"],
        "generated_at": generated.isoformat(timespec="seconds"),
        "data_sha256": sim.games_sha256(games, cfg26),
        "seasons": exp["seasons"],
        "legend": legend,
        "derivation_text": derivation_text,
        "data_source": "Oracle's Elixir (oracleselixir.com)",
        **(meta_extra or {}),
    }
    return files


def git_meta(exp: dict, pred: dict) -> dict:
    """Code, config and frozen-prediction identity recorded in meta.json."""
    return {
        "commit": sim._git("rev-parse", "HEAD"),
        # the output folder itself does not count: the previous export is not a code change
        "dirty_worktree": bool(
            sim._git("status", "--porcelain", "--", ".", f":(exclude){exp['out_dir']}")
        ),
        "config_sha256": hashlib.sha256(
            b"".join(p.read_bytes() for p in [*sim.CONFIG_FILES, EXPORT_CONFIG_PATH])
        ).hexdigest(),
        "frozen": {
            "tag": exp["frozen_tag"],
            "commit": pred["meta"]["commit"],
            "committed_utc": iso(exp["frozen_committed_utc"]),
            "output_commit": exp["frozen_output_commit"],
            "prediction_sha256": exp["frozen_prediction_sha256"],
        },
    }


# ---------- io ----------


def read_starts(path: Path) -> dict[str, pd.Timestamp | None]:
    """Series start times from the hand-entered results file (read only)."""
    series = yaml.safe_load(path.read_text())["series"]
    return {
        sid: score._utc(r["start_utc"]) if r.get("start_utc") else None
        for sid, r in series.items()
    }


def write_files(files: dict[str, object], out_dir: Path) -> int:
    """Write compact JSON; returns total bytes. Replaces the teams/ folder's old files."""
    out_dir = Path(out_dir)
    for old in (out_dir / "teams").glob("*.json"):
        old.unlink()
    total = 0
    for rel, obj in files.items():
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        path.write_text(text, encoding="utf-8")
        total += len(text.encode("utf-8"))
    return total


def main() -> None:
    if not sim.GAMES_PATH.exists():
        sys.exit(f"{sim.GAMES_PATH} not found: run python -m worlds.ingest first")
    exp = load_export_config()
    sc = yaml.safe_load(SCORE_CONFIG_PATH.read_text())
    check_pinned(
        Path(exp["frozen_prediction"]),
        exp["frozen_prediction_sha256"],
        "frozen prediction",
    )
    check_pinned(
        Path(exp["sensitivity"]), exp["sensitivity_sha256"], "sensitivity result"
    )
    pred = score.load_prediction(Path(exp["frozen_prediction"]))
    sens = json.loads(Path(exp["sensitivity"]).read_text())
    cfg_tag = score.tag_config(exp["frozen_tag"], pred)
    cfg26 = sim.load_config()
    doc_path = pick_score_file(exp["score_glob"])
    doc = json.loads(doc_path.read_text()) if doc_path else None
    if doc:
        check_score_results(doc, Path(exp["results_file"]))
    files = build_all(
        pd.read_parquet(sim.GAMES_PATH),
        exp,
        bt.load_config(),
        cfg26,
        pred,
        sens,
        cfg_tag,
        doc,
        doc_path.name if doc_path else None,
        read_starts(Path(exp["results_file"])),
        sc["quadrature_nodes"],
        git_meta(exp, pred),
    )
    total = write_files(files, Path(exp["out_dir"]))
    print(f"Wrote {len(files)} files, {total / 1e6:.2f} MB, to {exp['out_dir']}")
    print(
        f"score output: {doc_path.name if doc_path else 'none (2026 results pending)'}"
    )


if __name__ == "__main__":
    main()
