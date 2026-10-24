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

## 2026-10-23 — Time decay method: Option A (scale K by game age)
**Decision:** When replaying games in date order, scale each game's K by
`weight = exp(-ln2 * age_days / decay_half_life_days)`. Only games with `date < cutoff_date` are
used. `age_days = (cutoff_date - game_date)` in (fractional) days, measured from `cutoff_date`,
not from today and not from each later game. Games played during the tournament (in-tournament
updates in the backtest) get age 0, i.e. full K. Both teams in a game use the same scaled K, so
updates stay zero-sum. `decay_method` in `config/elo.yaml` selects `k_scale` (default) or `none`
(weight 1, plain Elo; the no-decay baseline for the half-life sweep).
**Alternatives considered:** Option B, pull ratings toward the (league) mean based on time since
last game (parked; to be compared with A later via `decay_method`). Measuring age from each
prediction date (rejected for now: requires a full replay per prediction).
**Evidence:** Pending. Compare `k_scale` vs `none` and half-lives of 91/182/365 days on the
Worlds 2023–2025 backtest once `backtest.py` works.
**Revisit if:** The backtest favours `none`, or once Option B is implemented.

## 2026-10-22 — Swiss records feed bracket seeding
**Decision:** The Swiss simulation returns every team's final (wins, losses) record, and the
knockout bracket is seeded from those records using rules in `config/worlds_2026.yaml`.
**Alternatives considered:** Return only qualified/eliminated lists and seed the bracket randomly
or by rating.
**Evidence:** Pending. Reasoning: real Worlds seeding depends on Swiss record, so title odds
for 3-0 teams should reflect their easier path.
**Revisit if:** The official 2026 seeding rules don't depend on record.

## 2026-10-22 — Ratings update during the tournament
**Decision:** In the backtest (and later live), ratings update game by game during Worlds: each
game is predicted from games strictly before it, then its result is added.
**Alternatives considered:** Freeze ratings at the tournament start date. Kept as a fallback
(`rating_updates: frozen` in `config/backtest.yaml`) in case the rolling version isn't ready
before Swiss starts.
**Evidence:** Pending. To test: compare in-tournament and frozen log loss on Worlds 2023–2025.
**Revisit if:** Rolling updates don't improve backtest log loss.

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

## 2026-10-24 — Ingest validation: raise on bad games, report unknown teams
**Decision:** `load_games` raises `ValueError` (listing gameids) for NaT dates and for any game whose
two rows don't share a date, have opposite sides, different teams (after aliasing) and exactly one
win. Rows are never dropped. Dates stay timezone-naive. Unknown team names and
`datacompleteness != "complete"` games are kept and returned by `ingest_report`; `main` refuses to
write parquet while unknown teams exist.
**Alternatives considered:** Warning instead of raising (lets a corrupt game into the ratings);
raising on unknown teams inside `load_games` (unusable while `canonical` is empty).
**Evidence:** `tests/test_ingest.py` (malformed-game cases, report, `compute_ratings` round trip).
**Revisit if:** Real Oracle's Elixir files contain rows that legitimately fail these checks (blank
team names in partial-data leagues), which would need an explicit exclusion list in `config/`.
