# Modelling decisions

A dated log of choices that affect the model. Newest entries go at the top.
Each entry: what was decided, what else was considered, the evidence, and when to revisit.
"Evidence: pending" is fine for early decisions, but update it once a backtest exists.

<!-- Template:
## YYYY-MM-DD — Short title
**Decision:**
**Alternatives considered:**
**Evidence:** (backtest log loss / Brier, data checks, reasoning)
**Revisit if:**
-->

## 2026-10-22 — Initial scope
**Decision:** Start with team-level Elo only. Player ratings, roster-change adjustments and Fearless
draft effects are parked.
**Alternatives considered:** Player-level ratings from the start; Riot solo queue data as an input.
**Evidence:** Pending. Reasoning: build the simplest baseline first so later additions can be judged
against it on the backtest. Solo queue data has no LPL coverage, so it can't be a required input.
**Revisit if:** The team-Elo baseline is done and backtested.

## 2026-10-22 — Data source and time decay
**Decision:** Oracle's Elixir match data from 2023 onward, with exponential time decay
(half-life ~6 months, configurable).
**Alternatives considered:** Shorter or longer half-life; no decay; including pre-2023 data.
**Evidence:** Pending. To test: compare half-lives of 3, 6 and 12 months, plus no decay, on the
Worlds 2023–2025 backtest.
**Revisit if:** The half-life sweep favours a different value.

## 2026-10-22 — Per-game probability constant within a series
**Decision:** Treat each game in a series as independent, with the same win probability p.
**Alternatives considered:** Shrinking late games toward 50% (Fearless effect); conditioning on
the series score.
**Evidence:** Pending. Simplest assumption; series maths can be tested exactly.
**Revisit if:** Backtest calibration on Bo5s is clearly off, or the Fearless work is unparked.

## 2026-10-22 — Simulation design
**Decision:** Monte Carlo of the Swiss Stage and knockouts, about 10,000 runs, with noise added to
ratings each run to represent rating uncertainty. Seeded for reproducibility.
**Alternatives considered:** Exact calculation (not practical for Swiss pairings); no rating noise.
**Evidence:** Pending. To check: title odds are stable across seeds at 10,000 runs.
**Revisit if:** Results vary too much between seeds.

## 2026-10-22 — Evaluation method
**Decision:** Backtest on Worlds 2023–2025. Main metric is log loss, also Brier score and a
calibration table. Compare against betting odds after removing the bookmaker margin.
**Alternatives considered:** Accuracy (rejected: ignores confidence).
**Evidence:** N/A (this sets the yardstick for every other decision).
**Revisit if:** Betting odds can't be found for enough matches.
