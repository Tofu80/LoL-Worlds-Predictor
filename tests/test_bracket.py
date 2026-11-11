import copy
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from worlds.bracket import simulate_bracket, validate_knockout
from worlds.series import bo5_rofs_win_prob

CFG = yaml.safe_load(Path("config/worlds_2026.yaml").read_text())
QF = CFG["knockout"]["quarterfinals"]
TEAMS = [t for pair in QF for t in pair]
STRENGTHS = {t: 1500.0 + 40 * i for i, t in enumerate(TEAMS)}
H, Q = 23.0, 0.2


def exact(strengths, h, q, cfg=CFG):
    """Exact stage probabilities, written independently of bracket.py."""
    res = cfg["swiss_results"]

    def series(a, b, g1):
        return bo5_rofs_win_prob(strengths[a], strengths[b], h, q, g1)

    def qf_g1(a, b):
        ra, rb = res[a], res[b]
        if ra == rb:
            return 0.5
        a_higher = (ra[0] - ra[1]) > (rb[0] - rb[1])
        return q if a_higher else 1 - q

    win = {}  # P(team wins its quarterfinal)
    for a, b in cfg["knockout"]["quarterfinals"]:
        p = series(a, b, qf_g1(a, b))
        win[a], win[b] = p, 1 - p
    sf, fin, title = dict(win), {}, {}
    pairs = cfg["knockout"]["semifinals"]
    qfs = cfg["knockout"]["quarterfinals"]
    reach_final = {}
    for i, j in pairs:
        side_a, side_b = qfs[i], qfs[j]
        for x in side_a:
            reach_final[x] = win[x] * sum(win[y] * series(x, y, 0.5) for y in side_b)
        for y in side_b:
            reach_final[y] = win[y] * sum(win[x] * series(y, x, 0.5) for x in side_a)
    fin = reach_final
    sides = [qfs[i] + qfs[j] for i, j in pairs]
    for me, other in ((0, 1), (1, 0)):
        for x in sides[me]:
            title[x] = fin[x] * sum(fin[y] * series(x, y, 0.5) for y in sides[other])
    return sf, fin, title


def run(n, seed, sigma=0.0, strengths=STRENGTHS, cfg=CFG):
    rng = np.random.default_rng(seed)
    counts = {t: {"semifinal": 0, "final": 0, "champion": 0} for t in strengths}
    order = ["quarterfinal", "semifinal", "final", "champion"]
    for _ in range(n):
        noisy = {t: s + rng.normal(0, sigma) for t, s in strengths.items()}
        out = simulate_bracket(noisy, H, Q, cfg, rng)
        for t, stage in out.items():
            for key in counts[t]:
                if order.index(stage) >= order.index(key):
                    counts[t][key] += 1
    return counts


def test_exact_enumeration_is_a_distribution():
    sf, fin, title = exact(STRENGTHS, H, Q)
    assert sum(title.values()) == pytest.approx(1.0)
    assert sum(fin.values()) == pytest.approx(2.0)
    assert sum(sf.values()) == pytest.approx(4.0)


def test_monte_carlo_matches_exact_enumeration_with_sigma_zero():
    n = 20000
    counts = run(n, seed=3)
    sf, fin, title = exact(STRENGTHS, H, Q)
    for t in TEAMS:
        for got, want in (
            (counts[t]["semifinal"], sf[t]),
            (counts[t]["final"], fin[t]),
            (counts[t]["champion"], title[t]),
        ):
            se = math.sqrt(want * (1 - want) / n)
            assert got / n == pytest.approx(want, abs=4 * se + 1e-9)


def test_exactly_one_champion_and_stage_counts():
    rng = np.random.default_rng(0)
    for _ in range(50):
        out = simulate_bracket(STRENGTHS, H, Q, CFG, rng)
        stages = list(out.values())
        assert set(out) == set(TEAMS)
        assert stages.count("champion") == 1
        assert stages.count("final") == 1
        assert stages.count("semifinal") == 2
        assert stages.count("quarterfinal") == 4


def test_same_seed_gives_identical_output():
    assert run(300, seed=5, sigma=50.0) == run(300, seed=5, sigma=50.0)
    assert run(300, seed=5, sigma=50.0) != run(300, seed=6, sigma=50.0)


def _with_qf(qf):
    cfg = copy.deepcopy(CFG)
    cfg["knockout"]["quarterfinals"] = qf
    return cfg


def test_team_twice_in_bracket_raises():
    qf = [list(p) for p in QF]
    qf[3][1] = qf[0][0]
    with pytest.raises(ValueError, match="twice"):
        validate_knockout(_with_qf(qf), STRENGTHS)


def test_odd_number_of_teams_raises():
    qf = [list(p) for p in QF]
    qf[3] = [qf[3][0]]
    with pytest.raises(ValueError):
        validate_knockout(_with_qf(qf), STRENGTHS)


def test_wrong_number_of_quarterfinals_raises():
    with pytest.raises(ValueError):
        validate_knockout(_with_qf([list(p) for p in QF[:3]]), STRENGTHS)


def test_team_without_strength_raises():
    strengths = {t: s for t, s in STRENGTHS.items() if t != "T1"}
    with pytest.raises(ValueError, match="T1"):
        validate_knockout(CFG, strengths)


def test_simulate_bracket_validates():
    qf = [list(p) for p in QF]
    qf[1][1] = qf[0][0]
    with pytest.raises(ValueError):
        simulate_bracket(STRENGTHS, H, Q, _with_qf(qf), np.random.default_rng(0))
