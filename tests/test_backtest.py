import dataclasses

import pandas as pd
import pytest

from worlds.backtest import BacktestResult, backtest_worlds


def test_backtest_worlds_raises_not_implemented():
    cutoff = pd.Timestamp("2025-10-01")
    pytest.raises(NotImplementedError, backtest_worlds, 2025, None, {}, cutoff)


def test_backtest_result_fields():
    names = {f.name for f in dataclasses.fields(BacktestResult)}
    assert names == {"log_loss", "brier", "n_games", "calibration", "odds_log_loss"}
