import pytest

from worlds.series import bo3_win_prob, bo5_win_prob, series_win_prob


def _brute_force_bo3(p: float) -> float:
    q = 1 - p
    return p**2 + 2 * p**2 * q  # win 2-0 + win 2-1


def _brute_force_bo5(p: float) -> float:
    q = 1 - p
    return p**3 + 3 * p**3 * q + 6 * p**3 * q**2  # win 3-0, 3-1, 3-2


def test_bo3_at_half():
    assert bo3_win_prob(0.5) == pytest.approx(0.5)


def test_bo5_at_half():
    assert bo5_win_prob(0.5) == pytest.approx(0.5)


def test_bo3_monotonic():
    assert bo3_win_prob(0.6) > bo3_win_prob(0.5) > bo3_win_prob(0.4)


def test_bo5_monotonic():
    assert bo5_win_prob(0.6) > bo5_win_prob(0.5) > bo5_win_prob(0.4)


@pytest.mark.parametrize("p", [0.3, 0.5, 0.7, 0.9])
def test_bo3_matches_brute_force(p: float):
    assert bo3_win_prob(p) == pytest.approx(_brute_force_bo3(p))


@pytest.mark.parametrize("p", [0.3, 0.5, 0.7, 0.9])
def test_bo5_matches_brute_force(p: float):
    assert bo5_win_prob(p) == pytest.approx(_brute_force_bo5(p))


def test_series_win_prob_bo1():
    assert series_win_prob(0.7, "bo1") == pytest.approx(0.7)


def test_series_win_prob_bo3():
    assert series_win_prob(0.7, "bo3") == pytest.approx(bo3_win_prob(0.7))


def test_series_win_prob_bo5():
    assert series_win_prob(0.7, "bo5") == pytest.approx(bo5_win_prob(0.7))


def test_series_win_prob_unknown_format():
    with pytest.raises(ValueError):
        series_win_prob(0.5, "bo7")
