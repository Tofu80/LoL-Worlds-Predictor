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
- **Hooks:** No custom hooks yet. Guardrails are permission rules in `.claude/settings.json`:
  `Edit(data/raw/**)` and `git add` on raw data are denied, force-pushes and pushes to `main`
  are denied, `--no-verify` and `--amend` are denied, and `git push`, `gh pr create` and
  `gh pr merge` ask first. The `security-guidance` plugin (user level) runs a security review
  after every commit, push and turn. Making that once per PR is pending (see the PR notes).
- **Custom commands:** `/worlds-pipeline` (`.claude/skills/worlds-pipeline/`) runs the data
  pipeline. No other commands yet.
- **Reviewer agent:** `leakage-reviewer` (`.claude/agents/leakage-reviewer.md`, Opus,
  read-only). It audits a diff for look-ahead leakage, silent row drops and invariant breaks.
  CLAUDE.md requires running it before every `gh pr create`.
- **CI:** `.github/workflows/ci.yml` runs `ruff check`, `ruff format --check` and `pytest` on
  every pull request and on pushes to `main`.

## Model routing

| Step | Model |
|---|---|
| Planning | Opus |
| Implementing | Sonnet (on trial from the ingest task) |
| Leakage review | Opus (saved `leakage-reviewer` agent) |
| Haiku | Only once `/worlds-pipeline` runs end to end |
| Security review | Once per PR |

Why: most of the cost was context (cache reads and creation), not output, so fewer turns and
smaller context matter as much as a cheaper model.

| Run | Models | Time to PR | Corrections | Output | Cache creation | Cache read |
|---|---|---|---|---|---|---|
| **Before:** Elo time-decay (PR #2), main session | claude-opus-5-5 | 13 min, tests green first run | none | 23,638 | 112,080 | 1,471,504 |
| Before: reviewer subagent | claude-opus-5-5 | | | 3,783 | 48,109 | 220,478 |
| Before: 3 per-commit security reviews | claude-opus-4-7 | | | 4,021 | 48,634 | 168,400 |
| **After:** ingest task | _(fill in)_ | _(fill in)_ | _(fill in)_ | _(fill in)_ | _(fill in)_ | _(fill in)_ |

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
