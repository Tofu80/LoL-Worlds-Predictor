import pytest

from worlds.ingest import load_games, write_processed


def test_load_games_raises_not_implemented():
    pytest.raises(NotImplementedError, load_games, None)


def test_write_processed_raises_not_implemented():
    pytest.raises(NotImplementedError, write_processed, None, "test")
