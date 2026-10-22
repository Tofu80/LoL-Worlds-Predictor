import pandas as pd
from numpy.random import Generator


def run_simulation(
    ratings: dict[str, float],
    config: dict,
    n_runs: int,
    rng: Generator,
    rating_noise: float,
) -> pd.DataFrame:
    """Monte Carlo simulation of Swiss + knockouts.

    Returns a DataFrame indexed by team with probability columns
    advance, semifinal, final, title. `title` sums to 1;
    `advance` sums to config["swiss"]["advance"].
    """
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError("simulation pipeline not wired yet")


if __name__ == "__main__":
    main()
