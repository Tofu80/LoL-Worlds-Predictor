import pytest

from worlds.swiss import simulate_swiss


def test_simulate_swiss_raises_not_implemented():
    pytest.raises(NotImplementedError, simulate_swiss, [], {}, None, {})
