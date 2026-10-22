---
name: worlds-pipeline
description: Run the full Worlds title-predictor pipeline end to end: check tests, ingest and validate Oracle's Elixir data, rebuild team Elo, backtest on Worlds 2023–2025, and simulate Worlds 2026. Use when Phu asks to run the pipeline, refresh the predictions, or update title odds.
disable-model-invocation: true
argument-hint: "[--runs N] [--seed S] [--force] [--snapshot NAME]"
---

# Worlds pipeline

Runs six stages in order. Each stage ends with a **gate**: checks that must pass before the next
stage starts. If a gate fails, stop, report which check failed and why, and do not continue unless
Phu passed `--force`. Never make a gate pass by loosening the check, editing a test, or changing
a constant in `config/`. Those are modelling decisions and belong to Phu (see CLAUDE.md).

This skill **runs** the pipeline. It does not write or fix pipeline code. If a stage fails because
code is missing or wrong, stop and report it. Fixes go through the normal workflow: plan, then a
feature branch, then tests.

Arguments: `$ARGUMENTS`
- `--runs N`: Monte Carlo runs. Default: `simulation_count` in `config/elo.yaml`.
- `--seed S`: random seed. Default: `random_seed` in `config/elo.yaml`.
- `--force`: continue past a failed gate, but mark the run `FORCED` in the summary.
- `--snapshot NAME`: after a PASSED run, copy `summary.md`, `odds.csv`, `ratings.csv` and
  `metrics.json` into `results/YYYY-MM-DD-NAME/` (e.g. `pre-swiss`, `post-swiss`, `final`). This
  folder is committed; `runs/` is not. Never snapshot a FORCED or STOPPED run; say why instead.
  Don't commit the snapshot yourself. Tell Phu it's ready to commit.

## Before starting

1. Read `CLAUDE.md`. Its hard rules apply to every stage, especially no look-ahead leakage and
   `data/raw/` being read-only.
2. Create today's run folder `runs/YYYY-MM-DD/`. If one already exists, add a suffix (`-2`, `-3`).
   All outputs go there. Never write into `data/raw/`.
3. Find the most recent previous run folder. Comparison checks use its `metrics.json`, `ratings.csv`
   and `odds.csv`. If there is no previous run, say so and treat comparison checks as
   informational only.
4. If a module raises `NotImplementedError`, stop at that stage and report it as **NOT BUILT**, not
   as a failure. This is expected while the project is being built. List which stages ran.

## Gate thresholds

These numbers are operating checks, not model constants. If Phu wants them tuned, propose moving
them to `config/pipeline.yaml`; don't change them here silently.

| Check | Threshold |
|---|---|
| Elo mean drift | ±5 from `initial_rating` |
| Minimum recent games per Worlds team | 20 in the last 365 days (warning only) |
| Large rating move since previous run | 150 points (warning only) |
| Coin-flip baseline log loss | ln 2 ≈ 0.693 |
| Allowed backtest regression | +0.01 pooled log loss vs previous run |
| Title-odds sum tolerance | 0.001 |
| Seed stability, top-5 title odds | < 1.5 percentage points |

## Stage 0: Code health

1. Run `pytest` and `ruff check .`.

**Gate 0:** both are clean. A failing test means the code can't be trusted, so don't run the model on it.

## Stage 1: New data check

Oracle's Elixir CSVs are downloaded by hand into `data/raw/`. This skill never downloads or edits them.

1. List the CSVs in `data/raw/` with their modified dates. Report any that are new or changed
   since the previous run.
2. Compare each CSV's column headers with the previous run's (saved as `runs/<date>/schema.json`;
   write one this run).

**Gate 1**
- At least one CSV covering 2023 onward exists.
- Column headers are unchanged. Oracle's Elixir sometimes renames or adds columns, and a changed
  schema stops the run so Phu can check it.
- If nothing changed since the previous run, say so and ask whether to continue anyway.

## Stage 2: Ingest and validate

1. Run the ingest step (`worlds.ingest`) to build the processed games table in `data/processed/`
   from team rows only (`position == "team"`).
2. Run these checks and write the results to `runs/<date>/validation.md`:

| Check | Fails when |
|---|---|
| Duplicate games | any `gameid` has more than 2 team rows |
| Both sides present | any `gameid` lacks exactly one Blue and one Red row |
| Result consistency | the two rows of a game don't contain exactly one win |
| Unknown teams | a `teamname` is missing from `config/team_aliases.yaml` and isn't already canonical |
| Dates | any game is dated in the future or before 2023-01-01 |
| League coverage | a major region (LCK, LPL, LEC, LTA or the current names) has no games in the last 60 days while its season is running |
| Incomplete data | `datacompleteness != "complete"`. Count these by league; don't fail or drop them silently. Results are usually still usable. |

**Gate 2**
- None of the failing checks fail.
- For unknown team names, stop and list them with their league and date range. Ask Phu to add
  the mappings to `config/team_aliases.yaml` rather than guessing. A wrong mapping, such as an
  academy team merged into its main roster, silently corrupts the ratings.

## Stage 3: Rebuild Elo

1. Compute current ratings with `worlds.elo.compute_ratings`, using the constants in
   `config/elo.yaml` and a `cutoff_date` of today. Use whatever decay method is implemented. If
   that method isn't recorded in `docs/decisions.md`, say so.
2. Save the ratings to `runs/<date>/ratings.csv`, sorted from highest to lowest, with each team's
   game count over the last 365 days.

**Gate 3 (sanity checks)**
- No rating is NaN or infinite.
- The mean rating is within ±5 of `initial_rating`, since Elo is zero-sum per game.
- Every team in `config/worlds_2026.yaml` has a rating.
- Warnings, not failures: teams with fewer than 20 games in the last 365 days, and teams that moved
  more than 150 points since the previous run (show their recent results so Phu can judge).
- Show the top 10.

## Stage 4: Backtest

1. Run `python -m worlds.backtest` on Worlds 2023, 2024 and 2025. Ratings start from games
   dated **before that tournament's start date** (passed as an explicit `cutoff_date`). With
   `rating_updates: in_tournament` in `config/backtest.yaml`, each Worlds game is then predicted
   from games strictly before it and added to the ratings afterwards; with `frozen`, ratings
   stay fixed at the start date. Report which mode ran. No game may ever be predicted using its
   own result or any later game. This is the most important rule in the pipeline. Before trusting the numbers, check in the code that every
   input (ratings, decay weights, any normalisation) respects the cutoff. If you can't confirm it,
   say so in the summary.
2. Report, per year and pooled:
   - log loss and Brier score
   - the calibration table
   - the coin-flip baseline (0.693)
   - de-vigged betting-odds log loss on the same matches, if odds data exists (otherwise say
     "no odds data yet")
3. Save to `runs/<date>/metrics.json`.

**Gate 4**
- Pooled log loss is below 0.693. Above that, the model is worse than a coin flip and something is broken.
- Pooled log loss is no more than 0.01 worse than the previous run. If it is, stop and show which
  year got worse.
- Report the gap to betting odds but don't gate on it. The market is the benchmark, not a pass mark.

If log loss changed because the model changed, remind Phu to record the before and after in
`docs/decisions.md`. Don't write that entry yourself.

## Stage 5: Simulate Worlds 2026

1. Run `python -m worlds.simulate` with the current ratings, the format in
   `config/worlds_2026.yaml`, the run count and seed from the arguments or config, and
   `rating_noise` from `config/elo.yaml`.
2. Save per-team probabilities to `runs/<date>/odds.csv`: advance from Swiss, reach quarterfinals
   (if separate), semifinals, finals, and win the title.

**Gate 5**
- Title probabilities across all teams sum to 1, within 0.001.
- Advance-from-Swiss probabilities sum to `swiss.advance` in the format config.
- Every team in the format config appears exactly once.
- Run again with seed + 1. The top-5 title odds should differ by less than 1.5 percentage points
  between the two seeds. If they differ more, the run count is too low; report it and suggest a
  higher count rather than changing the config.
- If `config/worlds_2026.yaml` still has its "verify against official rules" warning, include it
  in the summary.

## Final summary

Write `runs/<date>/summary.md` and show it to Phu. Keep it to one screen; details live in the
other files in the run folder.

- Status: PASSED, FORCED (list the failed gates), or STOPPED AT STAGE n (reason, or NOT BUILT).
- Data: new or changed CSVs, game counts, incomplete-data counts by league.
- Top 10 title odds, with the change since the previous run.
- Backtest log loss by year, compared with the coin flip, betting odds and the previous run.
- Warnings: thin data, large rating moves, unconfirmed leakage checks, unverified format.
- Assumptions still in place: constant per-game probability within a series, no Fearless effects,
  no player ratings or roster-change adjustments.
