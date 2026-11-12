"""Sensitivity runs of the frozen Worlds 2026 pre-quarterfinal prediction.

A variant is a small override file merged over the config read from tag pred-2026-preQF. Same
pre-cutoff data, ratings, H, q, sigma, n_runs and seed as the primary run; only the overridden
keys differ. The primary prediction stays the one reported and is never written. Post-cutoff
rows are loaded and format-checked by load_games, then cut at prediction_cutoff before any use;
none is printed.

    python -m worlds.sensitivity config/sensitivity/game1_coin_flip.yaml
"""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from worlds import simulate
from worlds.ingest import RAW_DIR, _validate, load_games
from worlds.score import (
    SCORE_CONFIG_PATH,
    load_prediction,
    series_prob,
    tag_config,
)

META_KEYS = ("variant", "out_stem")  # in the override file but not config keys
STAGES = ("semifinal", "final", "title")
OUT_DIR = Path("results")


def apply_override(base: dict, ov: dict) -> dict:
    """base with the override's keys replaced (dicts merge key by key). A key that base
    does not have raises, so a typo cannot silently leave the variant equal to the primary."""
    out = copy.deepcopy(base)
    for k, v in ov.items():
        if k in META_KEYS:
            continue
        if k not in out:
            raise ValueError(f"unknown override key {k!r}")
        if isinstance(v, dict):
            unknown = sorted(set(v) - set(out[k]))
            if unknown:
                raise ValueError(f"unknown override key(s) {unknown} under {k!r}")
            out[k].update(v)
        else:
            out[k] = v
    return out


def check_data(games: pd.DataFrame, pred: dict, cfg: dict) -> None:
    """Raise unless the pre-cutoff rows hash to the primary run's data_sha256."""
    got, want = simulate.games_sha256(games, cfg), pred["meta"]["data_sha256"]
    if got != want:
        raise ValueError(f"data_sha256 differs from the primary run: {got} != {want}")


def check_reproduces(pred: dict, result: dict) -> None:
    """Raise unless re-running the primary from the data gives the saved strengths, H, q, odds."""
    m = pred["meta"]
    if m.get("dirty_worktree"):
        raise ValueError("the primary was generated from a dirty worktree")
    table = result["table"].round(4)
    bad = [] if set(pred["odds"]) == set(table.index) else ["different teams"]
    bad += [
        f"strength {t}"
        for t, s in pred["strengths"].items()
        if abs(result["strengths"][t] - s) > 1e-9
    ]
    bad += [x for x in ("H", "q") if abs(result[x.lower()] - m[x]) > 1e-9]
    bad += [
        f"{t} {s}"
        for t, row in pred["odds"].items()
        for s, v in row.items()
        if t not in table.index or abs(table.loc[t, s] - v) > 1e-9
    ]
    if bad:
        raise ValueError(f"the primary does not reproduce from the data: {bad[:5]}")


def write_new(out_dir: Path, stem: str, doc: dict, md: str) -> list[Path]:
    """Write <stem>.json and <stem>.md; raises FileExistsError if either exists and
    ValueError for a stem that is a path or the primary's own name."""
    if Path(stem).name != stem or stem in ("", ".", "..") or stem == simulate.OUT_NAME:
        raise ValueError(f"bad out_stem {stem!r}")
    paths = [Path(out_dir) / f"{stem}.json", Path(out_dir) / f"{stem}.md"]
    existing = [p for p in paths if p.exists()]
    if existing:
        raise FileExistsError(f"{existing}: refusing to overwrite")
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    for p, text in zip(paths, (json.dumps(doc, indent=2, default=str), md)):
        with p.open("x") as fh:
            fh.write(text)
    return paths


def render_md(doc: dict) -> str:
    meta = doc["meta"]

    def d(a: float, b: float) -> str:
        return f"{b - a:+.3f}"

    lines = [
        f"# Worlds 2026 pre-quarterfinal sensitivity check: {meta['variant']}",
        "",
        "Robustness check only. Primary prediction unchanged; it is the one reported.",
        "Same pre-cutoff data, ratings, H, q, sigma, n_runs and seed; only the override differs.",
        "",
        *(f"- {k}: `{v}`" for k, v in meta.items() if k != "model"),
        f"- model: `{meta.get('model')}`",
        "",
        (
            "| team | P(SF) primary | variant | diff | P(final) primary | variant | diff "
            "| P(title) primary | variant | diff |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t, r in doc["teams"].items():
        cells = [
            f"{r['primary'][s]:.3f} | {r['variant'][s]:.3f} | {d(r['primary'][s], r['variant'][s])}"
            for s in STAGES
        ]
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Quarterfinal series, P(first team wins), averaged over the rating noise:",
        "",
        "| series | primary | variant | diff |",
        "|---|---|---|---|",
        *(
            f"| {s['a']} v {s['b']} | {s['primary']:.3f} | {s['variant']:.3f} | {d(s['primary'], s['variant'])} |"
            for s in doc["qf_series"]
        ),
        "",
        f"Max |change| in title odds: {doc['max_abs_title_change']:.3f}",
        "",
    ]
    return "\n".join(lines)


def run(override_path: Path) -> list[Path]:
    sc = yaml.safe_load(SCORE_CONFIG_PATH.read_text())
    pred = load_prediction(Path(sc["prediction"]))
    ov_text = Path(override_path).read_text()
    ov = yaml.safe_load(ov_text)
    base = tag_config(sc["tag"], pred)
    worktree = hashlib.sha256(
        b"".join(p.read_bytes() for p in simulate.CONFIG_FILES)
    ).hexdigest()
    if worktree != pred["meta"]["config_sha256"]:
        sys.exit("the worktree config no longer hashes to the primary's config_sha256")
    if simulate._git("status", "--porcelain"):
        sys.exit(
            "dirty worktree: commit or move the changes first (the primary was clean)"
        )
    variant = apply_override(base, ov)

    paths = sorted(RAW_DIR.glob("*.csv"))
    games = pd.concat([load_games(p) for p in paths], ignore_index=True)
    games = simulate._before_cutoff(
        games, base
    )  # drop everything from the cutoff on, unread
    _validate(games)
    check_data(games, pred, base)
    print("data hash matches the primary's data_sha256")

    m = pred["meta"]
    result = simulate.predict(
        games, base, m["n_runs"], np.random.default_rng(m["seed"])
    )
    check_reproduces(pred, result)
    print("primary reproduced from the data")

    table = simulate.run_simulation(
        pred["strengths"], m["H"], m["q"], variant, m["n_runs"],
        np.random.default_rng(m["seed"]), m["sigma"],
    ).round(4)  # fmt: skip
    teams = {
        t: {"primary": pred["odds"][t], "variant": table.loc[t].to_dict()}
        for t in pred["odds"]
    }
    qf = [
        {
            "a": a,
            "b": b,
            **{
                name: series_prob(
                    a, b, "quarterfinals", pred["strengths"], m["H"], m["q"], cfg,
                    m["sigma"], sc["quadrature_nodes"],
                )
                for name, cfg in (("primary", base), ("variant", variant))
            },
        }
        for a, b in base["knockout"]["quarterfinals"]
    ]  # fmt: skip
    meta = {
        **simulate.build_meta(result, base, games, m["seed"]),
        "variant": ov["variant"],
        "override": {
            "file": str(override_path),
            "sha256": hashlib.sha256(ov_text.encode()).hexdigest(),
            "content": {k: v for k, v in ov.items() if k not in META_KEYS},
        },
        "data_hash_matches_primary": True,
        "compared_to": {
            "file": sc["prediction"],
            "tag": sc["tag"],
            "commit": m["commit"],
            "config_sha256": m["config_sha256"],
        },
    }
    doc = {
        "meta": meta,
        "teams": teams,
        "qf_series": qf,
        "max_abs_title_change": max(
            abs(r["variant"]["title"] - r["primary"]["title"]) for r in teams.values()
        ),
    }
    return write_new(OUT_DIR, ov["out_stem"], doc, render_md(doc))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("override", type=Path)
    for p in run(ap.parse_args().override):
        print(f"Wrote {p}")


if __name__ == "__main__":
    main()
