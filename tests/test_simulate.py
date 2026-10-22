import numpy as np
import pytest

from worlds.simulate import run_simulation


def test_run_simulation_raises_not_implemented():
    rng = np.random.default_rng(0)
    pytest.raises(NotImplementedError, run_simulation, {}, {}, 10, rng, 0.0)
