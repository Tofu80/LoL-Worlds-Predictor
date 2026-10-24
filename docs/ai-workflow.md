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
- **Hooks:** One custom hook: after a successful `gh pr create`, it tells Claude to run
  `/security-review` and post the result on the PR. It exists because the plugin's push sweep did
  not fire on PR #4 or #5 (`~/.claude/security/log.txt`: "Push sweep: no push-success signal in
  bash output"), and the plugin deliberately ignores `gh pr create`. Guardrails are permission rules in `.claude/settings.json`:
  `Edit(data/raw/**)` and `git add` on raw data are denied, force-pushes and pushes to `main`
  are denied, `--no-verify` and `--amend` are denied, and `git push`, `gh pr create` and
  `gh pr merge` ask first. The `security-guidance` plugin (user level) used to review every
  commit and every turn. `.claude/settings.json` `env` now turns those off
  (`SECURITY_GUIDANCE_COMMIT_REVIEW=off`, `ENABLE_STOP_REVIEW=0`), leaving the push sweep,
  which reviews a branch's unreviewed commits in one pass. Commit and Stop reviews are
  confirmed off in `~/.claude/security/log.txt`; the push sweep firing once per push is not yet confirmed.
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
| **After:** ingest task, Opus | claude-opus-5-5 | 10m25s wall clock (about 3m40s active), tests green first run | none | 10,823 | 64,660 | 223,479 |
| After: ingest task, Sonnet | claude-sonnet-5-5 | | | 13,715 | 63,014 | 946,293 |
| After: reviewer subagent | claude-opus-5-5 | 7 findings (1 High) | | | | |

Ingest totals: 24,538 output / 127,674 cache creation / 1,169,772 cache read. Total output is
similar to the Elo task (24.5k vs 23.6k), so the two tasks are comparable in size, but this is one
task against one task, so it isn't evidence that Sonnet is cheaper.

Lesson: enter plan mode before Claude starts reading files. Reading first and planning after
builds the cache twice.

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
