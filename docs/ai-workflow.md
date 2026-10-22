# How I used AI (Claude Code) on this project

Short version: Claude Code wrote much of the code, but under rules, tests and reviews I set up so
that mistakes get caught. Modelling decisions are mine and are logged in [decisions.md](decisions.md).

## Setup

- **CLAUDE.md:** Project rules Claude reads every session: no look-ahead leakage, raw data is
  read-only, constants live in config, seeded simulations, never edit a test just to make it pass.
  When I correct Claude on the same thing twice, the fix becomes a rule here.
- **Plan before code:** For anything non-trivial (e.g. Swiss pairing), Claude proposes a plan
  and I approve or correct it first.
- **Tests first:** I write or approve tests for logic with known right answers (Elo update,
  Bo3/Bo5 maths, Swiss rules, odds summing to 100%), then Claude implements until they pass.
- **Hooks:** _(fill in once set up: e.g. run pytest + ruff after edits, block writes to data/raw/)_
- **Custom commands:** _(fill in: e.g. /backtest, /ingest)_
- **Reviewer agent:** _(fill in: a separate agent that audits diffs for leakage and maths bugs)_

## Where AI went wrong, and how it was caught

The most useful part of this file. Write entries as they happen.

<!-- Template:
### YYYY-MM-DD — Short title
**What Claude did:**
**How it was caught:** (test, backtest number, review, reading the code)
**Fix and new rule:** (what changed in code / CLAUDE.md / tests)
-->

_(none yet)_

## What I did myself

_(fill in: e.g. chose the Elo design and half-life from backtests, wrote the series-probability
tests, checked the Worlds format against the official rules)_

## What I'd do differently

_(fill in at the end)_
