def bo3_win_prob(p: float) -> float:
    return p**2 * (3 - 2 * p)


def bo5_win_prob(p: float) -> float:
    return p**3 * (10 - 15 * p + 6 * p**2)


def series_win_prob(p: float, format: str) -> float:
    match format.lower():
        case "bo1":
            return p
        case "bo3":
            return bo3_win_prob(p)
        case "bo5":
            return bo5_win_prob(p)
        case _:
            raise ValueError(f"Unknown series format: {format!r}")
