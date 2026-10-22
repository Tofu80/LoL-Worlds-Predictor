import pytest

from worlds.elo import expected_score, update_ratings


def test_expected_score_equal_ratings():
    assert expected_score(1500, 1500) == pytest.approx(0.5)


def test_expected_score_higher_rated_wins_more():
    assert expected_score(1600, 1500) > 0.5
    assert expected_score(1500, 1600) < 0.5


def test_expected_score_symmetry():
    assert expected_score(1600, 1500) == pytest.approx(1 - expected_score(1500, 1600))


def test_update_zero_sum():
    ra, rb = update_ratings(1500, 1500, result=1.0, k=32)
    delta_a = ra - 1500
    delta_b = rb - 1500
    assert delta_a == pytest.approx(-delta_b)


def test_update_fifty_fifty_moves_by_k_over_2():
    ra, rb = update_ratings(1500, 1500, result=1.0, k=32)
    assert ra - 1500 == pytest.approx(16.0)
    assert 1500 - rb == pytest.approx(16.0)


def test_update_winner_gains_loser_loses():
    ra, rb = update_ratings(1500, 1500, result=1.0, k=32)
    assert ra > 1500
    assert rb < 1500


def test_update_upset_gains_more():
    ra_upset, _ = update_ratings(1300, 1700, result=1.0, k=32)
    ra_expected, _ = update_ratings(1700, 1300, result=1.0, k=32)
    assert ra_upset - 1300 > ra_expected - 1700
