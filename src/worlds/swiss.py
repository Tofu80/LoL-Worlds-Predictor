from numpy.random import Generator


def simulate_swiss(
    teams: list[str],
    ratings: dict[str, float],
    rng: Generator,
    config: dict,
) -> dict[str, tuple[int, int]]:
    """Simulate the Swiss Stage.

    Returns {team: (wins, losses)}. Each team stops on the win target
    (qualified) or the loss target (eliminated); no rematches.
    """
    raise NotImplementedError
