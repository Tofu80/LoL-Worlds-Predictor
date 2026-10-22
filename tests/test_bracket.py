import pytest

from worlds.bracket import simulate_bracket


def test_simulate_bracket_raises_not_implemented():
    pytest.raises(NotImplementedError, simulate_bracket, {}, {}, None, {})
