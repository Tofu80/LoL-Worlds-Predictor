from numpy.random import Generator


def simulate_bracket(
    records: dict[str, tuple[int, int]],
    ratings: dict[str, float],
    rng: Generator,
    config: dict,
) -> dict[str, str]:
    """Simulate the knockout bracket, seeded from Swiss records.

    Returns {qualified team: furthest stage}, one of "quarterfinal", "semifinal",
    "final", "champion". Exactly one team is "champion".
    """
    raise NotImplementedError
