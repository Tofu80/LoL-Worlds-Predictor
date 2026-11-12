# LoL Worlds Predictor

Predicts title odds for League of Legends Worlds. Teams are rated with Elo (time decay, a blue-side term and
league offsets), and a Monte Carlo simulation of the knockout bracket turns the ratings into odds. The model is
backtested on Worlds 2023–2025. The Worlds 2026 result is a retroactive pre-quarterfinal prediction: data up to
the end of the Swiss stage, frozen and tagged before the final.

## Headline result: Worlds 2023–2025 backtest (n = 300 games)

Log loss per game, lower is better (n = 110 / 106 / 84 games in 2023 / 2024 / 2025). Brier is pooled only.

| model | 2023 | 2024 | 2025 | pooled log loss | pooled Brier |
|---|---|---|---|---|---|
| **current** (blue-side term H + league offsets) | 0.6470 | 0.6974 | 0.6348 | **0.6614** | 0.2334 |
| original Elo | 0.6998 | 0.7299 | 0.6788 | 0.7045 | 0.2549 |
| blue-only (always favour blue, no team ratings) | 0.6872 | 0.6841 | 0.6954 | 0.6884 | 0.2476 |
| constant 0.5 | 0.6931 | 0.6931 | 0.6931 | 0.6931 | 0.2500 |

Log loss is the average penalty for the probability given to what actually happened, and it punishes confident
wrong calls hardest. Always saying 50% scores ln 2 = 0.693, so that is the coin-flip line a model has to beat.

The first Elo was worse than a coin flip (0.7045). Fixing the blue-side advantage and regional rating drift
brought it to 0.6614. A paired bootstrap of the pooled log-loss change against the original Elo gives −0.0432,
95% CI [−0.0804, −0.0053]. Nearly all of that gain comes from the league offsets; the blue-side term alone is not
significant (−0.0047, 95% CI [−0.0119, +0.0023]). The league-offset step size (`k_league`) was fit on 2023–24;
2025 was used only in the merge check that it did not get worse. See [docs/decisions.md](docs/decisions.md) (2026-10-26).

## Worlds 2026: pre-quarterfinal prediction

A retroactive pre-quarterfinal prediction: data up to the end of the Swiss stage, frozen and tagged before the
final. It uses only games before 2026-11-02 00:00 UTC. It was produced on 2026-11-10, after quarterfinal results
were public, and tagged on 2026-11-12, so it was not public before the knockouts. Source: [results/worlds_2026_preQF.md](results/worlds_2026_preQF.md).

| team | P(SF) | P(final) | P(title) | What happened |
|---|---|---|---|---|
| Gen.G | 0.957 | 0.767 | 0.550 | TODO after final |
| Bilibili Gaming | 0.636 | 0.459 | 0.194 | TODO after final |
| T1 | 0.860 | 0.295 | 0.082 | TODO after final |
| Dplus Kia | 0.364 | 0.232 | 0.074 | TODO after final |
| Invictus Gaming | 0.504 | 0.106 | 0.048 | TODO after final |
| Top Esports | 0.496 | 0.117 | 0.048 | TODO after final |
| LYON | 0.043 | 0.010 | 0.002 | TODO after final |
| Karmine Corp | 0.140 | 0.014 | 0.002 | TODO after final |

> **TODO after final:** scorer results (`python -m worlds.score`) and the comparison with TAB bookmaker odds.

The market comparison covers the final only: no quarterfinal or semifinal odds were captured. The knockout is 7
series, which is too few to judge the model either way.

## How it works

1. **Data:** Oracle's Elixir match results, team rows only.
2. **Ratings:** Elo with exponential time decay (182-day half-life), a blue-side term H (23.3 Elo points for 2026,
   from the pre-cutoff blue win rate) and league offsets that move only on international games.
3. **Series:** per-game probability to a Bo5 probability. Knockout series use a Right of First Selection side
   model, where the previous game's loser tends to take red (the holder is on blue with probability q = 0.218,
   estimated from 1,736 pre-cutoff games). Swiss and the backtest use a constant per-game probability.
4. **Simulation:** 10,000 Monte Carlo runs of the bracket with rating noise (σ = 50), fixed seed 42.
5. **Evaluation:** log loss, Brier score and calibration tables on Worlds 2023–2025.

## How leakage is prevented

- **Cutoff rule:** to predict a game at time t, only games with `date < t` are used, compared on the full UTC
  timestamp. The 2026 prediction drops every row from 2026-11-02 00:00 UTC on, after the whole CSV has been loaded
  and format-checked.
- **Game by game:** in the backtest each game is predicted first and its result is added afterwards.
- **Frozen and tagged (tamper evidence, not a leakage proof; see Limitations):** the tag `pred-2026-preQF` points at commit `1efe4e7`. The output records the config hash
  (`fe2d60db…`), the pre-cutoff data hash (`3281b29a…`), H, q, sigma and seed. The scorer refuses to run unless
  the tag's commit and config hash match the saved prediction and a re-run of the saved simulation reproduces
  the saved odds.
- **Review:** a read-only `leakage-reviewer` agent is required before every pull request (CLAUDE.md); each finding
  is fixed with a test or listed in the PR.
- **Pre-registered sensitivity check:** re-running with a coin flip for who picks side in quarterfinal game 1
  changes no title odds by more than 0.002
  ([results](results/worlds_2026_preQF_sens_game1coin.md)). It was committed before it ran, but it was specified
  after the QF and SF results were public, so it was not chosen blind.

## Limitations

- The scorer's `check_prediction` proves the saved odds follow from the saved inputs. It does not prove those inputs
  came from pre-cutoff data.
- The CSV snapshot behind the prediction was taken on 2026-11-10, after the cutoff, so later corrections by
  Oracle's Elixir to pre-cutoff rows are possible.
- The side model (who holds side choice, reusing q for game 1) and sigma = 50 were decided after quarterfinal
  results were public. They were not tuned on any 2026 knockout result, but that cannot be proven from the code.
- TES–IG game 1: the model uses a coin flip for who picks side where the ruleset uses draw order. The effect is
  about 1pp on that series.
- Team-level only: no player ratings, roster-change adjustments or Fearless draft effects.
- The backtest choices (league offsets, `k_league`) were made while looking at the 2023–2025 results, so those
  numbers are not a clean out-of-sample test.
- The 2026 sample is 7 series.

## Run it

```
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m worlds.ingest        # first: writes data/processed/games.parquet
python -m worlds.backtest      # Worlds 2023–2025: current vs +H vs +H+league vs blue-only vs 0.5, k_league grid, bootstrap CI, calibration by matchup class
python -m worlds.simulate      # regenerates the frozen pre-QF prediction (refuses to overwrite)
python -m worlds.sensitivity config/sensitivity/game1_coin_flip.yaml  # pre-QF robustness check (clean tree; refuses to overwrite)
python -m worlds.score         # score the frozen pre-QF prediction vs real results (--partial if the final isn't in)
```

## Data and credits

Match data is from [Oracle's Elixir](https://oracleselixir.com), downloaded by hand into `data/raw/`. Those files
are **not committed** (too large for GitHub) and are never modified; all cleaning happens in code. Create
`data/raw/` yourself before running the ingest step.

- [Modelling decisions](docs/decisions.md)
- [How I used AI on this project](docs/ai-workflow.md)
