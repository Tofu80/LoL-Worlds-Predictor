# Project Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the complete skeleton project layout — directories, config, module stubs, and test scaffolding — so `pytest` and `ruff` pass, every `python -m worlds.*` command in CLAUDE.md has an entry point (unbuilt stages fail loudly with `NotImplementedError`), and the two math modules (series, elo) have full TDD implementations. Stub interfaces match what `/worlds-pipeline` (`.claude/skills/worlds-pipeline/SKILL.md`) expects.

## Revision notes (v2, 2026-10-22) — awaiting Phu's approval

Changes from v1 (original kept at `2026-10-22-project-layout.orig.md`):

1. **pyproject.toml:** `build-backend` fixed to `setuptools.build_meta`. v1's `setuptools.backends.legacy:build` doesn't exist, so `pip install -e` would fail.
2. **Backtest:** `backtest_worlds` takes an explicit `cutoff_date` (the tournament start) and returns a `BacktestResult` with calibration and betting-odds fields. Tournament start dates live in a new `config/backtest.yaml` (left `null` to fill from official sources). Ratings update game by game during the tournament: each game is predicted using only games strictly before it, then added to the ratings. `config/backtest.yaml` has a `rating_updates` switch (`in_tournament` or `frozen`) so the simpler frozen version stays available if the rolling one isn't ready before Swiss.
3. **Simulation:** `run_simulation` takes a `numpy.random.Generator` (hard rule 4: passed in, not built from a seed inside) and returns a DataFrame of per-stage probabilities (`advance`, `semifinal`, `final`, `title`), not only title odds. `simulate_bracket` returns each team's furthest stage so those columns can be filled. `simulate_swiss` returns every team's final (wins, losses) record, and `simulate_bracket` takes those records so seeding can follow them. The seeding rules go in `worlds_2026.yaml` once checked against the official rules.
4. **Format config:** `worlds_2026.yaml` gains a `teams:` list. `team_aliases.yaml` gains a `canonical:` list so the "unknown team" check has something to check against. New tests keep aliases, teams and canonical names consistent.
5. **Entry points:** `ingest`, `backtest` and `simulate` get a `main()` plus `if __name__ == "__main__"`. For now `main()` raises `NotImplementedError`, which `/worlds-pipeline` reports as NOT BUILT.
6. **Stub tests:** these are explicitly marked as placeholders to be replaced when a module is implemented, so replacing them isn't "changing a test to make it pass".
7. **Lint:** steps now say to run `ruff check --fix`. Current ruff versions sort imports by default, so v1's code would fail `ruff check` as written.
8. **Task 6:** no longer creates `docs/decisions.md` and `docs/ai-workflow.md`, which already exist with more detail and would be overwritten. It now commits `.claude/` (skill and `settings.json`) and this plan, adds a README data note, and opens a pull request instead of merging locally, because `main` is protected on GitHub.

**Decided by Phu (2026-10-22):**
- **In-tournament ratings:** update game by game during the tournament. Frozen-at-start stays as a config fallback depending on how much is done before Swiss starts.
- **Swiss → bracket seeding:** Swiss returns records now and the bracket is seeded from them.

- **`runs/`:** not committed (in `.gitignore`), and not created by this plan. `/worlds-pipeline` creates run folders only when it runs. Key runs (e.g. pre-Swiss, post-Swiss, final) are copied into a committed `results/` folder with `/worlds-pipeline --snapshot <name>`, which gives a dated record of predictions made before results were known.
- **`data/raw/`:** CSV contents are git-ignored (the folder stays via `.gitkeep`). The README says where to download them.

**Still open:**
- **Live 2026 simulation:** with game-by-game updates, re-running `simulate` mid-Worlds would also need the results already played (fixed, not simulated). Out of scope for this skeleton; raise it when `simulate.py` is built.

**Architecture:** One branch `setup/project-layout` installs the package via pyproject.toml, defines all constants in YAML, implements series.py and elo.expected_score fully (well-defined invariants), stubs the remaining modules with typed signatures, and places test files ready for subsequent TDD. Merges into `main` after all tests pass.

**Tech Stack:** Python 3.10+, pytest, ruff, pandas, numpy, pyarrow, pyyaml, setuptools

## Global Constraints

- Python >=3.10; type hints on every public function
- All constants in `config/`; no magic numbers in `src/`
- `data/raw/` is never written to
- Simulations use a seeded `numpy.random.Generator`, never global state
- `ruff check . && ruff format .` must pass before any commit. Current ruff versions also sort imports, which the code blocks below don't do, so run `ruff check --fix . && ruff format .` after writing each file rather than reporting a lint failure.
- `pytest` must pass (or exit 0 with no errors) before merging to `main`
- Branch name: `setup/project-layout`
- Every function that reads match data for a past tournament takes an explicit `cutoff_date`. With in-tournament updates, each game is predicted only from games strictly before it (no same-game or later-game data).
- Stub tests asserting `NotImplementedError` are placeholders. Replacing them with real tests when a module is implemented is expected and does not break hard rule 5.

---

### Task 1: Branch, directories, and infrastructure

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `data/raw/.gitkeep`
- Create: `data/processed/.gitkeep`
- Create: `notebooks/.gitkeep`
- Create: `src/worlds/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: `import worlds` works; `pytest` discovers `tests/`; `ruff check .` runs

- [ ] **Step 1: Create branch**

```bash
git checkout -b setup/project-layout
```
Expected: `Switched to a new branch 'setup/project-layout'`

- [ ] **Step 2: Create directories and placeholder files**

```bash
mkdir -p data/raw data/processed config src/worlds tests notebooks docs
touch data/raw/.gitkeep data/processed/.gitkeep notebooks/.gitkeep
touch src/worlds/__init__.py tests/__init__.py
```

- [ ] **Step 3: Write .gitignore**

```
.venv/
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.pytest_cache/
.ruff_cache/
*.parquet
data/processed/
# Raw Oracle's Elixir CSVs are large (close to GitHub's 100 MB file limit).
# Download them yourself; see README "Data". Keep the folder in git.
data/raw/*
!data/raw/.gitkeep
# Pipeline run folders are local only. Key runs are copied to results/ (committed).
runs/
.DS_Store
```

- [ ] **Step 4: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "worlds-predictor"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.25",
    "pyarrow>=12.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "ruff>=0.1",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 88
target-version = "py310"
```

- [ ] **Step 5: Install the package**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```
Expected: `Successfully installed worlds-predictor-0.1.0 ...`

- [ ] **Step 6: Verify tools run**

```bash
python -c "import worlds"
pytest --collect-only
ruff check .
```
Expected: no errors; `pytest` prints `0 items` or similar.

- [ ] **Step 7: Commit**

```bash
git add .gitignore pyproject.toml data/ notebooks/ src/ tests/
git commit -m "chore: scaffold directories and install infrastructure"
```

---

### Task 2: Config files

**Files:**
- Create: `config/elo.yaml`
- Create: `config/worlds_2026.yaml`
- Create: `config/team_aliases.yaml`
- Create: `config/backtest.yaml`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(path)` not yet needed — tests call `yaml.safe_load` directly; later tasks import these files via a helper
- `worlds_2026.yaml["teams"]`: list of canonical team names (empty until the field is confirmed)
- `team_aliases.yaml["canonical"]`: list of current team names; `["aliases"]`: old name → canonical name
- `backtest.yaml["tournaments"][year]["start_date"]`: the cutoff for that year's backtest

- [ ] **Step 1: Write failing test**

File: `tests/test_config.py`

```python
from pathlib import Path
import yaml

CONFIG = Path("config")

def test_elo_config_has_required_keys():
    cfg = yaml.safe_load((CONFIG / "elo.yaml").read_text())
    for key in ("k_factor", "initial_rating", "decay_half_life_days",
                "simulation_count", "rating_noise", "random_seed"):
        assert key in cfg, f"Missing key: {key}"

def test_worlds_2026_has_required_keys():
    cfg = yaml.safe_load((CONFIG / "worlds_2026.yaml").read_text())
    assert "swiss" in cfg
    assert "knockout" in cfg

def test_team_aliases_loadable():
    cfg = yaml.safe_load((CONFIG / "team_aliases.yaml").read_text())
    assert "aliases" in cfg
    assert "canonical" in cfg


def test_aliases_point_to_canonical_names():
    cfg = yaml.safe_load((CONFIG / "team_aliases.yaml").read_text())
    canonical = set(cfg["canonical"])
    for old, new in cfg["aliases"].items():
        assert new in canonical, f"{old!r} maps to unknown team {new!r}"


def test_worlds_2026_teams_are_valid():
    fmt = yaml.safe_load((CONFIG / "worlds_2026.yaml").read_text())
    canonical = set(
        yaml.safe_load((CONFIG / "team_aliases.yaml").read_text())["canonical"]
    )
    teams = fmt["teams"]
    assert isinstance(teams, list)
    assert len(teams) == len(set(teams)), "duplicate team in worlds_2026.yaml"
    assert set(teams) <= canonical, "team missing from canonical list"
    if teams:  # empty until the qualified field is confirmed
        assert len(teams) == fmt["swiss"]["total_teams"]


def test_backtest_years_configured():
    cfg = yaml.safe_load((CONFIG / "backtest.yaml").read_text())
    assert set(cfg["tournaments"]) == {2023, 2024, 2025}
    assert cfg["rating_updates"] in {"in_tournament", "frozen"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```
Expected: FAIL — `config/elo.yaml` not found.

- [ ] **Step 3: Write config/elo.yaml**

```yaml
k_factor: 32
initial_rating: 1500
decay_half_life_days: 182
simulation_count: 10000
rating_noise: 50
random_seed: 42
```

- [ ] **Step 4: Write config/worlds_2026.yaml**

```yaml
# WARNING: verify these rules against official Riot 2026 Worlds announcement
# before running any simulation. Do not assume format from memory.
year: 2026
# Canonical names (must appear in team_aliases.yaml "canonical").
# Fill in from the official qualified-teams list.
teams: []
swiss:
  total_teams: 16
  advance: 8
  eliminate: 8
  win_target: 3    # wins to qualify
  loss_target: 3   # losses to be eliminated
  bo1_rounds: [1, 2, 3]
  bo3_rounds: [4, 5]
knockout:
  # How Swiss records map to bracket slots (e.g. 3-0 teams vs 3-2 teams,
  # same-region avoidance). Fill in from the official rules.
  seeding: null
  quarterfinals: bo5
  semifinals: bo5
  final: bo5
```

- [ ] **Step 5: Write config/team_aliases.yaml**

```yaml
# canonical: every current team name the model knows. A name in the data that is
#            neither canonical nor an alias is "unknown" and stops /worlds-pipeline.
# aliases:   alternate or historical name -> canonical name.
# Example:   canonical: ["Cloud9"]   aliases: {"Cloud9 Gold": "Cloud9"}
canonical: []
aliases: {}
```

- [ ] **Step 5b: Write config/backtest.yaml**

```yaml
# Start date of each Worlds. Ratings are built from games with
# date < start_date; games from start_date on are the ones evaluated.
# Fill in from official sources. Do not assume from memory.
#
# rating_updates:
#   in_tournament: predict each Worlds game from all games strictly before it,
#                  then add it to the ratings (decided 2026-10-22)
#   frozen:        ratings fixed at start_date for the whole tournament (fallback)
rating_updates: in_tournament
tournaments:
  2023: {start_date: null}
  2024: {start_date: null}
  2025: {start_date: null}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add config/ tests/test_config.py
git commit -m "feat: add config YAML files with Elo constants and 2026 format placeholder"
```

---

### Task 3: series.py — full TDD

**Files:**
- Create: `tests/test_series.py`
- Create: `src/worlds/series.py`

**Interfaces:**
- Produces:
  - `bo3_win_prob(p: float) -> float`
  - `bo5_win_prob(p: float) -> float`
  - `series_win_prob(p: float, format: str) -> float`  — `format` is `"bo1"`, `"bo3"`, or `"bo5"`

- [ ] **Step 1: Write failing tests**

File: `tests/test_series.py`

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_series.py -v
```
Expected: FAIL — `cannot import name 'bo3_win_prob'`.

- [ ] **Step 3: Implement series.py**

File: `src/worlds/series.py`

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_series.py -v
ruff check src/worlds/series.py tests/test_series.py
```
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/worlds/series.py tests/test_series.py
git commit -m "feat: implement Bo3/Bo5 series win probability formulas"
```

---

### Task 4: elo.py — TDD for unambiguous functions, stub the rest

**Files:**
- Create: `tests/test_elo.py`
- Create: `src/worlds/elo.py`

**Interfaces:**
- Produces:
  - `expected_score(rating_a: float, rating_b: float) -> float`
  - `update_ratings(rating_a: float, rating_b: float, result: float, k: float) -> tuple[float, float]`  — `result` is `1.0` if A won, `0.0` if B won; returns `(new_a, new_b)`. **No time-decay here** — decay approach TBD (flag for Phu before implementing `compute_ratings`).
  - `compute_ratings(games: pd.DataFrame, cutoff_date: pd.Timestamp, k: float, initial_rating: float, decay_half_life_days: int) -> dict[str, float]` — stubbed, raises `NotImplementedError`

- [ ] **Step 1: Write failing tests**

File: `tests/test_elo.py`

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_elo.py -v
```
Expected: FAIL — `cannot import name 'expected_score'`.

- [ ] **Step 3: Implement elo.py**

File: `src/worlds/elo.py`

```python
import pandas as pd


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def update_ratings(
    rating_a: float,
    rating_b: float,
    result: float,
    k: float,
) -> tuple[float, float]:
    ea = expected_score(rating_a, rating_b)
    new_a = rating_a + k * (result - ea)
    new_b = rating_b + k * ((1 - result) - (1 - ea))
    return new_a, new_b


def compute_ratings(
    games: pd.DataFrame,
    cutoff_date: pd.Timestamp,
    k: float,
    initial_rating: float,
    decay_half_life_days: int,
) -> dict[str, float]:
    # TIME-DECAY APPROACH: two options to discuss with Phu before implementing:
    #   A) Scale K by exp(-ln2 * age_days / half_life) when replaying each game.
    #   B) Decay each team's rating toward initial_rating between gaps in play.
    # Option A is more common in sports models. Raise before implementing.
    raise NotImplementedError("Time-decay Elo formula not yet decided — see comment above")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_elo.py -v
ruff check src/worlds/elo.py tests/test_elo.py
```
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/worlds/elo.py tests/test_elo.py
git commit -m "feat: implement Elo expected_score and update_ratings; stub compute_ratings pending decay decision"
```

---

### Task 5: Remaining module stubs

**Files:**
- Create: `src/worlds/ingest.py`
- Create: `src/worlds/swiss.py`
- Create: `src/worlds/bracket.py`
- Create: `src/worlds/simulate.py`
- Create: `src/worlds/backtest.py`
- Create: `tests/test_ingest.py`
- Create: `tests/test_swiss.py`
- Create: `tests/test_bracket.py`
- Create: `tests/test_simulate.py`
- Create: `tests/test_backtest.py`

**Interfaces:**
- Produces (stubs only — all raise NotImplementedError):
  - `ingest.load_games(path: Path) -> pd.DataFrame`
  - `ingest.write_processed(df: pd.DataFrame, name: str) -> Path`
  - `swiss.simulate_swiss(teams, ratings, rng, config) -> dict[str, tuple[int, int]]`: team → final (wins, losses). Every team ends on `swiss.win_target` wins or `swiss.loss_target` losses (3 each at Worlds); qualified teams are those that hit the win target.
  - `bracket.simulate_bracket(records, ratings, rng, config) -> dict[str, str]`: takes the Swiss records and seeds by `config["knockout"]["seeding"]`; returns qualified team → furthest stage reached, one of `"quarterfinal"`, `"semifinal"`, `"final"`, `"champion"`
  - `simulate.run_simulation(ratings, config, n_runs, rng, rating_noise) -> pd.DataFrame`: index = team; columns `advance`, `semifinal`, `final`, `title` (probabilities). `title` sums to 1; `advance` sums to `swiss.advance`.
  - `backtest.backtest_worlds(year, games, config, cutoff_date) -> BacktestResult`: dataclass with `log_loss`, `brier`, `n_games`, `calibration` (DataFrame), `odds_log_loss` (`float | None`, None when no odds data)
  - `main()` in `ingest`, `simulate` and `backtest`, so `python -m worlds.<module>` runs. Raises `NotImplementedError` until the pipeline is wired; argparse (`--runs`, `--seed`) is added at that point.

- [ ] **Step 1: Write stub tests (import + NotImplementedError checks)**

These are placeholders. Replace each file with real tests when its module is implemented.

File: `tests/test_ingest.py`
```python
import pytest
from worlds.ingest import load_games, write_processed


def test_load_games_raises_not_implemented():
    pytest.raises(NotImplementedError, load_games, None)


def test_write_processed_raises_not_implemented():
    pytest.raises(NotImplementedError, write_processed, None, "test")
```

File: `tests/test_swiss.py`
```python
import pytest
from worlds.swiss import simulate_swiss


def test_simulate_swiss_raises_not_implemented():
    pytest.raises(NotImplementedError, simulate_swiss, [], {}, None, {})
```

File: `tests/test_bracket.py`
```python
import pytest
from worlds.bracket import simulate_bracket


def test_simulate_bracket_raises_not_implemented():
    pytest.raises(NotImplementedError, simulate_bracket, {}, {}, None, {})
```

File: `tests/test_simulate.py`
```python
import numpy as np
import pytest
from worlds.simulate import run_simulation


def test_run_simulation_raises_not_implemented():
    rng = np.random.default_rng(0)
    pytest.raises(NotImplementedError, run_simulation, {}, {}, 10, rng, 0.0)
```

File: `tests/test_backtest.py`
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ingest.py tests/test_swiss.py tests/test_bracket.py tests/test_simulate.py tests/test_backtest.py -v
```
Expected: FAIL — import errors.

- [ ] **Step 3: Write stub modules**

File: `src/worlds/ingest.py`
```python
from pathlib import Path
import pandas as pd

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")


def load_games(path: Path) -> pd.DataFrame:
    """Load and validate an Oracle's Elixir CSV; return team rows only (position == 'team')."""
    raise NotImplementedError


def write_processed(df: pd.DataFrame, name: str) -> Path:
    """Write df to data/processed/<name>.parquet; return the path written."""
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError("ingest pipeline not wired yet")


if __name__ == "__main__":
    main()
```

File: `src/worlds/swiss.py`
```python
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
```

File: `src/worlds/bracket.py`
```python
from numpy.random import Generator


def simulate_bracket(
    records: dict[str, tuple[int, int]],
    ratings: dict[str, float],
    rng: Generator,
    config: dict,
) -> dict[str, str]:
    """Simulate the knockout bracket, seeded from Swiss records.

    Returns {qualified team: furthest stage}, one of "quarterfinal", "semifinal",
    "final", "champion". Exactly one team is "champion".
    """
    raise NotImplementedError
```

File: `src/worlds/simulate.py`
```python
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
```

File: `src/worlds/backtest.py`
```python
from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestResult:
    log_loss: float
    brier: float
    n_games: int
    calibration: pd.DataFrame
    odds_log_loss: float | None  # None when no betting-odds data


def backtest_worlds(
    year: int,
    games: pd.DataFrame,
    config: dict,
    cutoff_date: pd.Timestamp,
) -> BacktestResult:
    """Backtest one Worlds starting at cutoff_date.

    Ratings start from games with date < cutoff_date. With
    rating_updates == "in_tournament", each Worlds game is predicted from
    games strictly before it, then added to the ratings; with "frozen",
    ratings stay fixed at cutoff_date.
    """
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError("backtest pipeline not wired yet")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_ingest.py tests/test_swiss.py tests/test_bracket.py tests/test_simulate.py tests/test_backtest.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Run full test suite + lint**

```bash
pytest -v
ruff check . && ruff format --check .
```
Expected: all pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/worlds/ tests/
git commit -m "feat: add typed stubs for ingest, swiss, bracket, simulate, backtest"
```

---

### Task 6: Commit skill and plan, open a PR into main

`docs/decisions.md` and `docs/ai-workflow.md` already exist and are more detailed than v1's
versions, so this task does **not** create or overwrite them. Modelling decisions are logged by Phu.

**Files:**
- Commit: `.claude/skills/worlds-pipeline/SKILL.md`
- Commit: `docs/superpowers/plans/2026-10-22-project-layout.md`
- Commit: `.claude/settings.json`
- Modify: `README.md`

**Interfaces:**
- Produces: a pull request from `setup/project-layout` into `main`

- [ ] **Step 1: Run full test suite one final time**

```bash
pytest -v
ruff check . && ruff format --check .
```
Expected: all pass.

- [ ] **Step 2: Commit the pipeline skill and this plan**

```bash
git add .claude/skills/worlds-pipeline/SKILL.md .claude/settings.json docs/superpowers/plans/2026-10-22-project-layout.md
git commit -m "docs: add /worlds-pipeline skill, agent permissions and project-layout plan"
```

- [ ] **Step 3: Add a "Data" section to README.md and commit**

State that the Oracle's Elixir match-data CSVs (2023 onward) are downloaded by hand from
oracleselixir.com into `data/raw/`, are not committed, and are never modified.

```bash
git add README.md
git commit -m "docs: explain where raw match data comes from"
```

- [ ] **Step 4: Push the branch and open a pull request**

`main` is protected on GitHub (no direct pushes), so the merge happens through a PR.

```bash
git push -u origin setup/project-layout
gh pr create --fill --base main
```

Then stop and tell Phu the PR is ready. Phu reviews and merges it on GitHub (or approves
`gh pr merge --merge` when asked).

- [ ] **Step 5: Verify on main after the merge**

```bash
git checkout main && git pull
pytest -v
ruff check .
python -m worlds.simulate   # expected: NotImplementedError (NOT BUILT), not ModuleNotFoundError
```
Expected: tests and lint pass; the module entry point exists.

- [ ] **Step 6 (Phu, manual):** add a `docs/decisions.md` entry for the open time-decay choice
  (K-scaling vs. decay toward the initial rating).
