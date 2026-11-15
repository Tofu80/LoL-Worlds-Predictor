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

### 2026-10-22 — Swiss format written from general knowledge
**What Claude did:** Claude Code wrote the `config/worlds_2026.yaml` placeholder (c56185d, Oct 22) with
`bo1_rounds: [1, 2, 3]` and `bo3_rounds: [4, 5]` from general knowledge. The file had a "verify against the
official announcement" warning at the top, but the values looked like facts.
**How it was caught:** Desktop Claude flagged the config as wrong on Oct 24 while looking up the real 2026 format
in a planning chat (project handover, not recorded in the repo). The real rule: a Bo3 whenever a team can qualify or be eliminated (a 2-x or
x-2 record), Bo1 otherwise.
**Fix and new rule:** Fixed Nov 10 in PR #14 (d23db71, `bo3_when_record_has: 2`). It never reached any output,
because the 2026 prediction is knockout-only. The fix was checked against two news pages
(decisions.md, 2026-11-10), not an official rulebook. CLAUDE.md: "Check it against the official rules. Don't
assume it from memory."

### 2026-10-24 — Blank gameids could pair rows across games
**What Claude did:** Claude Code (Sonnet) wrote the ingest in PR #5. A blank `gameid` was skipped by `groupby`,
and `elo.py` then cross-joined those rows into fake games.
**How it was caught:** The Opus `leakage-reviewer`, rated High.
**Fix and new rule:** Fixed with a test (d5a3cdc): blank gameids and games with no team rows now raise.
decisions.md (2026-10-24, ingest validation): raise on a bad game, never drop rows silently.

### 2026-10-24 — A reviewer finding silently skipped
**What Claude did:** Claude Code (Sonnet), PR #5. The reviewer returned 7 findings (1 High). One Low was neither
fixed nor listed in the PR description: an empty or malformed alias file raised `TypeError` or `KeyError` instead
of a clear `ValueError`.
**How it was caught:** Desktop Claude spotted it when reviewing the PR #5 results and token report with Phu
(planning chat, not the repo).
**Fix and new rule:** Fixed in PR #6 (6c7f7a2). CLAUDE.md: every finding is either fixed with a test or listed in
the PR description as an open decision.

### 2026-10-24 — Team identity judged on names and dates
**What Claude did:** Claude Code (Sonnet), PR #8. It kept `Team Secret` (EWC 2026) separate from
`Team Secret Whales` because the EWC games fell in different weeks and looked like a name reuse. It also left
two sets of academy rosters playing under main-team names in the data: KeSPA Cup (2024–26 editions; in 2026 T1, Gen.G,
Hanwha Life, Dplus Kia and KT Rolster) and CDF (Team BDS and Karmine Corp in the 2023 run-up to Worlds). Both fed
the main teams' Elo.
**How it was caught:** Phu's playername scans. Both Team Secret names fielded the same five players (Bie, Dire,
Eddie, Hizto, Pun), and the KeSPA Cup rosters were academy players. The CDF rosters were found in a follow-up
playername check during PR #9's leakage review, and Phu then decided to exclude them.
**Fix and new rule:** Fixed in PR #9 (1979bb8, 3c68e8b): an EWC-only league alias to Team Secret Whales, and
`excluded_leagues: [KeSPA Cup, CDF]` (166 and 141 games dropped). CLAUDE.md "Data notes": alias and
team-identity decisions use playername overlap as evidence, not just leagues and dates.

### 2026-11-09 — Side choice assumed to mean blue
**What Claude did:** Desktop Claude (the Nov 9 planning prompt) assumed the Right of First Selection holder
takes blue side, as the side-selection method did in earlier Worlds.
**How it was caught:** In planning, before any code: the holder can choose side or draft order, so "holder takes
blue" did not follow.
**Fix and new rule:** Replaced by the revised option 2 (decisions.md, 2026-11-10): model side only, and estimate
q from pre-cutoff games instead of assuming it. The estimate came later: q = 0.218 from 1,736 games, so the
previous loser was on blue about 22% of the time.

### 2026-11-12 — Final's start time written from memory
**What Claude did:** Desktop Claude's 2026-11-12 handover put the final at 03:00 Sydney (16:00 UTC). It was written
from memory, not the official schedule.
**How it was caught:** TAB listed the match at 6:00 Sydney. The Oracle's Elixir CSV later showed game 1 starting at
2026-11-14 19:53 UTC (06:53 Sydney), and this was noticed while filling in the results file.
**Fix and new rule:** Effect: the closing odds snapshot (14:02 UTC) was taken about 6 hours before the start, not the
planned 2. It was still valid, because the scorer only needs a snapshot strictly before the start. Rule: a claim about
when something happens comes from an official or dated source, not a summary.

### 2026-11-13 — "Committed before the matches" was not true
**What Claude did:** Desktop Claude's brief for the website defined the `frozen` label as "the tagged
pred-2026-preQF prediction, committed before the matches". Written from the project summary, not from git.
**How it was caught:** Claude Code, in plan mode, before any code: `git log` shows the prediction output was
committed on 2026-11-10 (1efe4e7 at 22:52:38 +11:00, output in 08e0ebe two seconds later), a week after the
quarterfinals started on Nov 3; the tag came on Nov 12. Only the final was played after the commit. decisions.md
(2026-11-10) already said the prediction was retroactive.
**Fix and new rule:** The label wording is now "computed from games before the 2026-11-02 cutoff, committed
2026-11-10 after the quarterfinals had started, never re-run", and each knockout match says whether it was played
before or after the commit (decisions.md, 2026-11-13). Rule: a claim about when something happened comes from git
history or a dated log entry, not from a summary.

## What I did myself

I made the modelling decisions; Claude Code wrote almost all of the code. The decisions were:
time decay by scaling K (option A), the blue-side term H, league offsets, the merge bar C, how side
selection is modelled (option 2) and the rating noise sigma. For each one Claude laid out the options
and I picked, and the choice and the evidence for it are in decisions.md.

Where I knew the domain, I caught things the AI didn't. Claude Code judged team identity on names and
dates; my playername scans showed that both Team Secret names fielded the same five players, and that
KeSPA Cup and CDF games were academy rosters playing under main-team names. I also found the official
2026 ruleset and checked the side-selection rules against it.

I set the integrity rules for the prediction: data only from before the cutoff, freeze and tag it before
the final, and score it exactly once. I chose TAB as the odds benchmark, recorded the snapshots myself
and checked every knockout result against Leaguepedia before it was scored.

I also decided what not to build. Player ratings, roster-change adjustments and Fearless draft effects
stayed parked, so the project could ship before Worlds ended.

## What I'd do differently

**Understand before building, not after.** I worked with a "build now, understand later" mindset. I
used Claude Code to build, but much less to understand what it was building. The log above shows where
that cost me. The mistakes I caught myself were all in areas I already knew: rosters, team identity,
the tournament rules. The mistakes in the maths and the code, such as blank gameids being cross-joined
into fake games, were caught by the reviewer agent, not by me. I could approve a plan without being
able to check it.

Next time I'd learn the core concepts before or while building them, not after:
- the maths: how an Elo update works, the series probability formulas, log loss and Brier score, what
  a bootstrap confidence interval does and doesn't tell you;
- the code: how pandas groupby and merges behave with missing values, and where look-ahead leakage
  can creep into a pipeline.

In practice that means explaining a plan back in my own words before approving it, writing the tests
for known-answer logic myself, and reading the diffs for the core modules (elo.py, series.py, score.py)
rather than relying on the tests and the reviewer.

**Smaller, process-level changes:**
- Check the official format before writing any config, not after.
- Design the integrity protocol before the live window. The pre-quarterfinal prediction ended up
  retroactive (committed after the quarterfinals had started), because the protocol came late.
- Capture odds as they are posted, so every round has a market comparison, not just the final.
- Run playername identity checks from day one.
