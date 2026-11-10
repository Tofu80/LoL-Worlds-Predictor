from numpy.random import Generator

from worlds.series import bo5_rofs_win_prob

STAGES = ("quarterfinal", "semifinal", "final", "champion")


def validate_knockout(config: dict, strengths: dict[str, float]) -> None:
    """Raise ValueError unless the bracket is 4 quarterfinals of 2 distinct teams,
    each team appears once, and every team has a strength."""
    ko = config["knockout"]
    qfs = ko["quarterfinals"]
    if len(qfs) != 4 or any(len(p) != 2 for p in qfs):
        raise ValueError(f"expected 4 quarterfinals of 2 teams, got {qfs!r}")
    teams = [t for pair in qfs for t in pair]
    dupes = sorted({t for t in teams if teams.count(t) > 1})
    if dupes:
        raise ValueError(f"team(s) appear twice in the bracket: {dupes}")
    missing = sorted(set(teams) - set(strengths))
    if missing:
        raise ValueError(f"no strength for bracket team(s): {missing}")
    if sorted(i for pair in ko["semifinals"] for i in pair) != [0, 1, 2, 3]:
        raise ValueError(
            f"semifinals must use each quarterfinal once: {ko['semifinals']!r}"
        )


def _swiss_rank(config: dict, team: str) -> int:
    wins, losses = config["swiss_results"][team]
    return wins - losses


def game1_blue_prob(round_name: str, a: str, b: str, q: float, config: dict) -> float:
    """A's probability of being on blue in game 1. The RoFS holder is on blue with
    probability q; a coin flip for the holder gives 0.5."""
    rule = config["rofs_game1"][round_name]
    if rule == "coin_flip":
        return 0.5
    if rule == "higher_seed":
        ra, rb = _swiss_rank(config, a), _swiss_rank(config, b)
        return 0.5 if ra == rb else (q if ra > rb else 1 - q)
    raise ValueError(f"unknown rofs_game1 rule {rule!r} for {round_name}")


def simulate_bracket(
    strengths: dict[str, float],
    h: float,
    q: float,
    config: dict,
    rng: Generator,
) -> dict[str, str]:
    """Play the fixed knockout bracket once; every series is a RoFS Bo5.

    strengths: {team: rating (+ league offset, + noise)}. Returns {team: furthest
    stage}, one of STAGES; exactly one team is "champion".
    """
    validate_knockout(config, strengths)
    ko = config["knockout"]
    stage = {t: STAGES[0] for pair in ko["quarterfinals"] for t in pair}

    def play(round_name: str, a: str, b: str) -> str:
        p = bo5_rofs_win_prob(
            strengths[a],
            strengths[b],
            h,
            q,
            game1_blue_prob(round_name, a, b, q, config),
        )
        return a if rng.random() < p else b

    winners = [play("quarterfinals", *pair) for pair in ko["quarterfinals"]]
    finalists = []
    for i, j in ko["semifinals"]:
        stage[winners[i]] = stage[winners[j]] = STAGES[1]
        finalists.append(play("semifinals", winners[i], winners[j]))
    champion = play("final", *finalists)
    for t in finalists:
        stage[t] = STAGES[2]
    stage[champion] = STAGES[3]
    return stage
