# LoL Worlds Predictor

Predicts title odds for League of Legends Worlds 2026 using team Elo ratings and a Monte Carlo
simulation of the Swiss Stage and knockouts.

> **Status:** early development. Results below are placeholders.

## Headline result

_(fill in: backtest log loss on Worlds 2023–2025 vs. betting odds)_

## How it works

1. **Data:** Oracle's Elixir match results (2023 onward), weighted by recency (~6-month half-life).
2. **Ratings:** Team Elo, with cross-region strength coming from international events.
3. **Series:** Per-game win probability → Bo1/Bo3/Bo5 win probability.
4. **Simulation:** ~10,000 runs of the full tournament, with noise added to ratings each run.
5. **Evaluation:** Backtest on Worlds 2023–2025 (log loss, Brier, calibration) against betting odds.

## Current title odds

_(fill in: table or chart)_

## Run it

```
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m worlds.simulate
```

## Limitations

- Per-game win probability is assumed constant within a series (no Fearless draft effects yet).
- Team-level only: no player ratings or roster-change adjustments yet.
- _(add more as found)_

## More

- [Modelling decisions](docs/decisions.md)
- [How I used AI on this project](docs/ai-workflow.md)
