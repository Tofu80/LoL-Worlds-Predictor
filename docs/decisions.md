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

## 2026-11-12 — Sensitivity check: coin flip for QF game 1
**Decision:** `python -m worlds.sensitivity config/sensitivity/game1_coin_flip.yaml` re-runs the frozen pre-QF prediction with
`rofs_game1.quarterfinals = coin_flip` (primary: `higher_seed`). The check was named as a possible sensitivity check in the 2026-11-10 integrity note; the override file and code were
committed before the run (64171d4, then the run), and it ran on 2026-11-12, before the final. Caveat: the variant was specified
after the QF and SF results were public, so git ordering shows it was committed before the run, not that it was chosen blind. It varies only who holds the right of first selection in QF game 1; SF and
final were already coin flips, and TES-IG (equal records) is a coin flip in both. Everything else is identical: pre-cutoff data
(`prediction_cutoff` 2026-11-02T00:00 UTC), saved strengths, H, q, sigma 50, n_runs 10000, seed 42. The override is merged over the config
read from tag `pred-2026-preQF` and is not in `simulate.CONFIG_FILES`, so the primary config hash `fe2d60db…` is unchanged.
**Data:** the Nov 12 CSV's pre-cutoff rows hash to `3281b29a…`, equal to the primary's `data_sha256` (the run exits otherwise), and the
primary's odds were reproduced from the data before the variant ran. The run does not use or print any knockout result, but `load_games` loads and format-checks the whole CSV (post-cutoff rows included) before the cut.
Only the 2026 CSV's sha256 is recorded (`csv_snapshot`); the 2023-25 files are covered by the data hash only.
**Result:** max |change| in title odds is 0.002 (Bilibili Gaming -0.0020, Dplus Kia +0.0015; 3 dp in the .md); max |change| in P(SF) is 0.005. QF1 Dplus Kia
v Bilibili Gaming moves 0.369 -> 0.375, QF2 0.142 -> 0.139, QF3 and QF4 move by 0.001 or less. **Primary prediction unchanged**: it
stays the one reported and scored; the variant never replaces it. Output: `results/worlds_2026_preQF_sens_game1coin.{json,md}`.
**Open (Phu chose):** scoring the variant is a follow-up PR (`worlds.score --prediction <file>`), not built here.
**Alternatives considered:** a CLI flag (not pre-registered in git, nothing to hash) and editing `worlds_2026.yaml` (changes the hash).

## 2026-11-12 — Scoring the frozen pre-QF prediction (D1-D3, Phu)
**Decision:** `python -m worlds.score [--partial]` scores `results/worlds_2026_preQF.json` (tag `pred-2026-preQF` -> 1efe4e7)
against the real knockout. It loads the saved prediction and never writes it; it refuses to run unless the tag's commit and
config hash match the saved meta and a re-run of the saved simulation (saved strengths, H, q, sigma, n_runs, seed) reproduces the
saved odds. Output goes to `results/worlds_2026_preQF_score[_partial][_vN].{json,md}` and is never overwritten.
- **D1 (results source):** hand-entered `config/worlds_2026_results.yaml` (per series: start, winner, score, per game blue team and
  winner), cross-checked against the Oracle's Elixir CSV when it has the games (mismatch raises; absent = reported "unverified").
  Alternative: CSV only (rejected: it can lag days behind the final). Risk: typos, caught by the internal consistency checks.
- **D2 (what is scored):** series P(A wins | A meets B) = the sim's RoFS Bo5 model averaged over the rating noise,
  E over d ~ N(0, sigma*sqrt 2) of `bo5_rofs_win_prob(sA + d, sB, H, q, game-1 rule)`, by Gauss-Hermite quadrature (41 nodes, no RNG).
  The sim adds one N(0, 50) per team per run and holds it for the whole bracket, so this equals the sim for QFs; for SF and the final
  it ignores the selection effect (a team that advanced tended to have positive noise), so it is slightly less favourable to
  advancing underdogs than the sim's own conditional. Alternatives: sim-conditional Monte Carlo (noisy, rare matchups have almost no
  samples), noise-free strengths (more extreme than anything the sim produced). Round level uses the saved P(SF)/P(final)/P(title)
  (8 teams per round, scored only once the round is fully decided). Game level: P(blue wins) from the cutoff ratings, frozen (no
  in-knockout updates), with the real blue side. Baselines: constant 0.5 (round level: every series 0.5, i.e. 0.5/0.25/0.125) and
  blue-only (equal strengths, blue bonus H only; the game-level rate is the one H was fitted on).
- **D3 (odds):** hand-entered snapshots `results/odds/worlds_2026_<series>_<timestamp>.yaml` (schema in `config/score.yaml`). The latest
  snapshot strictly before the series start is used; later ones are reported and ignored. Margin removed by normalising implied
  probabilities to sum to 1; log loss compared on the series that have odds only. Caveat: SF/final odds know the earlier results, the
  frozen model does not. No snapshot files: skipped, and the output says so.
**Evidence:** `tests/test_score.py` (conditional series probability vs brute-force enumeration and a dense integral, round scoring with
hand values, margin removal, incomplete-results refusal, no-overwrite, mismatch with the saved prediction raises). On made-up results the
re-derived QF probabilities match the saved sim odds to Monte Carlo error (e.g. QF4 Gen.G 0.956 vs 0.957).
**Game level and noise:** per-game P(blue) also averages over the noise independently per game, but the sim holds one noise draw per team
for the whole bracket, so games within a series are correlated and the selection effect applies to SF/final games too. Not corrected.
**Leakage review (2026-11-12):** no look-ahead found. Fixed with tests: dirty-worktree prediction refused; `start_utc` after the first CSV
game raises; unknown post-cutoff WLDs team names raise (missing alias); skipped odds snapshots are listed; tied snapshots raise;
`--partial` with nothing finished refuses and counts games of unfinished series. Open: `check_prediction` proves internal consistency
(saved odds follow from saved strengths/H/q under the tagged config) but not that those inputs came from pre-cutoff data.
**Limit:** n is 7 series, about 25-35 games and 8 items per round; no conclusion about model quality can come from this alone.
Run on the real results after the final in a follow-up commit.

## 2026-11-10 — Retroactive pre-quarterfinal prediction: integrity note
**Decision:** `python -m worlds.simulate` produces the Worlds 2026 pre-quarterfinal prediction using only games with
`date < 2026-11-02T00:00:00` UTC (`prediction_cutoff`). Rows from the cutoff on are dropped right after loading, before
any validation, rating or print. The prediction was produced in Nov 2026, after some knockout games had been played.
Model choices (K, half-life, H, league offsets, `k_league`) were fixed by the 2023-25 backtest (PR #13) before this work;
the new pieces (RoFS side model, sigma = 50) were chosen without looking at any 2026 knockout result. No 2026 data after
the cutoff was used, and this PR loads, prints and compares no knockout result. A later PR compares the prediction with
what happened. Any re-run (new CSV, config or code) is a new version and does not replace this one; the output records
the commit, a config hash, the CSV sha256, H, q, sigma and seed. Phu tags the merged commit `pred-2026-preQF`.
**Known limit (open, leakage review):** the RoFS design (holder rule, reusing q for game 1, the league list and the 4 h gap) was
decided 2026-11-09, after the QFs had started and were public, and the format sources were read 2026-11-10. The code cannot prove
those choices were made blind to knockout side selections; it can only state that they were not tuned on any 2026 knockout result.
A coin-flip-for-game-1 variant is a possible sensitivity check.
**Snapshot caveat:** the pre-cutoff rows come from a 2026-11-10 CSV snapshot, and alias/config edits are dated after the cutoff, so
the output is not proven identical to what was knowable on Nov 1 (Oracle's Elixir may have corrected rows since).
**Alternatives considered:** Re-fitting on 2026 data (rejected: breaks "choices fixed by the backtest only").
**Evidence:** `tests/test_simulate.py::test_post_cutoff_results_change_nothing` (flipping knockout and other post-cutoff
results leaves the output identical), `test_game_exactly_at_cutoff_is_not_used`.

## 2026-11-10 — Knockout series use a Right-of-First-Selection side model (Phu 2026-11-09, revised option 2)
**Decision:** For knockout Bo5s the per-game win probability is `p_A = q_A*E(sA+H, sB) + (1-q_A)*E(sA, sB+H)` where
`q_A` is A's probability of being on blue. This replaces "p constant within a series" for knockout series (Swiss and the
backtest keep the constant-p functions). The RoFS holder picks side OR draft order; only side is modelled (no draft-order
term). Holder: QF game 1 = better Swiss record (equal records, TES vs IG: coin flip); SF and final game 1 = coin flip;
games 2+ = loser of the previous game. The holder is on blue with probability q, estimated from 2026 games before the
cutoff: the share of games 2+ (same two teams, < 4 h after the previous game) in LCK, LPL, LEC, LCS, CBLOL, LCP, WLDs, MSI,
FST, EWC, ASI where the previous loser played blue. The same q is used for game 1. `series.bo5_rofs_win_prob` is an exact
recursion over (wins A, wins B, previous loser) and matches brute-force enumeration over 5-game paths and side outcomes.
With H = 0 it equals p^3(10-15p+6p^2) for every q; with q = 0.5 it equals the side-neutral average.
**Unconfirmed assumption:** the game-1 holder rule follows Worlds' historical side-selection methods and has NOT been
checked against the 2026 Worlds ruleset (neither source page mentions side selection).
**Alternatives considered:** Constant p for knockouts (ignores that the loser tends to take red); modelling first pick /
draft order (first-pick teams win ~51%, not measurable); q = 0.5.
**Evidence:** The effect is under 1pp per series either way. Real q and n are printed by `python -m worlds.simulate`.
**Revisit if:** The 2026 ruleset says otherwise, or q is far from ~0.2.

## 2026-11-10 — Swiss format fix and 2026 dates
**Decision:** `config/worlds_2026.yaml`: Bo3 only when a team in the match has a 2-x or x-2 record (qualifying or
elimination match), Bo1 otherwise (replaces the wrong `bo1_rounds`/`bo3_rounds`). Knockout is the fixed official draw,
all Bo5: QF1 Dplus Kia v Bilibili Gaming, QF2 Karmine Corp v T1 (-> SF1), QF3 Top Esports v Invictus Gaming,
QF4 Gen.G v LYON (-> SF2). `start_date` 2026-10-15 (play-in), `swiss_start` 2026-10-23, `prediction_cutoff`
2026-11-02T00:00 UTC (last Swiss day Oct 31 US, first QF Nov 3 ~22:00 UTC).
**Evidence:** itemgame.com/en-id/blog/worlds-2026-quarterfinals-schedule-bracket-swiss-results and
riftdaily.com/lol-worlds-2026-knockout-stage/ (format, records, bracket); lolesports.com/en-US/news/msi-and-worlds-updates and
exitlag.com/news/worlds-2026-play-in-stage/ (dates, as returned by a search snippet, not read in full). Cross-checked
against the data: the first WLDs game on/after each date falls on that UTC day (`tests/test_real_data.py`). WLDs-labelled
games before `start_date` (regional qualifiers) are counted and reported, not treated as play-in or Swiss.
**Gap check (Phu 2026-11-10):** the 'no game between the last Swiss game and the cutoff' rule only counts games in an
international league or involving one of the 16 teams. The real data has 9 LAS academy games on 2026-11-01 05:10-11:42 UTC
(T1 / Dplus Kia / Hanwha Life / HANJIN BRION academy rosters) in the gap; they are counted and ignored. Playername check (2026 CSV): none of the 22 players in those games appears on
the pre-cutoff rosters of the 9 teams concerned (the 8 qualifiers' teams and Hanwha Life), so they are academy rosters, not
mislabelled main-roster games. A null or `unknown team` name in the gap counts as relevant and raises.
**Revisit if:** An official page gives different dates.

## 2026-10-26 — Blue-side bonus H and league offsets (merge bar C: PASS)
**Decision (Phu, 2026-10-26):** (1) Blue gets +H Elo in `expected_score`, in predictions and updates.
`H = 400*log10(r/(1-r))`, r = blue win rate over the 365 days before `cutoff_date` (all leagues): 21.5 / 23.1 /
23.2 for 2023 / 2024 / 2025. Fixed per tournament, not tuned on the backtest. (2) `strength = team + league[key]`.
A team's key is the league of its most recent non-international game before the game (`date < t`). Only
international games between two different keys move league ratings (`k_league` x decay weight, zero-sum);
domestic games move teams only. (3) Merge bar C: `k_league` from {8, 16, 32, 64} on 2023-24 only; merge if pooled
log loss < 0.7045 and 2025 does not get worse.
**Lineage (approved in plan mode):** `LTA N` -> `LCS` key, `LTA S` -> `CBLOL` key; the `LTA` label (40 NA-vs-BR
cross-conference games) updates teams only and never sets membership; `LCP` starts at the team-count-weighted mean
of PCS 3 / LJL 3 / VCS 4 (LCO teams and new entrants left out). Major set for the split: LCK, LPL, LEC, LCS.
**Alternatives considered:** Keeping league membership at the latest game of any kind (rejected: includes
international games); LTA S as a CBLOL/LLA mix; a league-mean regress (decay Option B, parked).
**Evidence:** `python -m worlds.backtest`, log loss (n = 110 / 106 / 84 / 300):

| variant | 2023 | 2024 | 2025 | pooled | Brier |
|---|---|---|---|---|---|
| current (PR #11) | 0.6998 | 0.7299 | 0.6788 | 0.7045 | 0.2549 |
| +H | 0.6925 | 0.7212 | 0.6823 | 0.6998 | 0.2528 |
| +H +league (k_league 64) | 0.6470 | 0.6974 | 0.6348 | 0.6614 | 0.2334 |
| blue-only (pre-cutoff r) | 0.6872 | 0.6841 | 0.6954 | 0.6884 | 0.2476 |
| 0.5 | | | | 0.6931 | 0.2500 |

k_league grid (pooled 2023-24, +H on): 8 -> 0.6942, 16 -> 0.6853, 32 -> 0.6748, 64 -> 0.6717. Paired bootstrap
(2000 resamples of games) of pooled log loss vs current: +H -0.0047, 95% CI [-0.0119, +0.0023]; +H +league -0.0432,
95% CI [-0.0804, -0.0053]. Merge bar: 0.6614 < 0.7045 and 2025 0.6348 <= 0.6788, PASS.
Favourite's view by matchup class (current -> +H +league): major-minor (n=70) mean predicted 0.639 / observed 0.400
-> 0.658 / 0.614; major-major (n=141) 0.593 / 0.539 -> 0.679 / 0.617; same-league (n=58) 0.599 / 0.517 -> 0.612 / 0.552;
minor-minor (n=31) 0.580 / 0.677 -> 0.635 / 0.742. Classes use the league keys at prediction time of the +H +league run.
**Caveats:** (a) The best `k_league` is the top of the grid (64), so the optimum may be higher; the grid was not extended
(Phu's grid). (b) +H alone is not significant (CI spans 0), the gain is the league term. (c) Teams that play two
domestic leagues at once (Deep Cross Gaming and Ground Zero in LCP+PCS, QT DIG in LCP+LJL, Disguised/Cupid in
LCS+NACL) flip keys with their latest game. (d) League ratings are not decayed between international events.
(e) Calibration is still over-confident for major-major and minor-minor favourites (n small).
**Revisit if:** A wider grid moves `k_league`; league ratings drift across a long gap without internationals.

## 2026-10-24 — First backtest baseline (Elo is not yet better than a coin flip)
**Decision:** `backtest_worlds` scores every WLDs game on or after `start_date` (play-in start) in
the same calendar year, per game (not per series), from p(blue wins). Games sharing a timestamp are all
predicted before any of them updates the ratings. `cutoff_date > start_date` raises (a scored game's
result would already be in the starting ratings). Non-WLDs and qualifier games after the cutoff update
ratings without being scored. Config: K=32, initial 1500, `k_scale`, half-life 182 days.
**Alternatives considered:** Sequential (date, gameid) updates (a same-timestamp game could see its
neighbour's result); scoring qualifiers (not the Worlds field).
**Evidence:** `python -m worlds.backtest`, log loss / Brier (0.5 baseline: 0.6931 / 0.2500):

| mode | 2023 (n=110) | 2024 (n=106) | 2025 (n=84) | pooled (n=300) |
|---|---|---|---|---|
| in_tournament | 0.6998 / 0.2526 | 0.7299 / 0.2663 | 0.6788 / 0.2434 | 0.7045 / 0.2549 |
| frozen | 0.7103 / 0.2580 | 0.7597 / 0.2786 | 0.7083 / 0.2555 | 0.7272 / 0.2646 |

In-tournament updates beat frozen in every year (pooled 0.7045 vs 0.7272), but both are worse than
constant 0.5. Pooled calibration (in_tournament, favourite's view): [0.5,0.6) n=154 predicted 0.548,
observed 0.455; [0.6,0.7) n=118, 0.643 vs 0.602; [0.7,0.8) n=27, 0.742 vs 0.519; [0.8,0.9) n=1.
Favourite accuracy 51.7% (SE about 2.9% at n=300). Flipping the predictions is worse (0.7500), so it
is not an inverted sign. Blue side won 55.3% of the scored games (56.4% of all WLDs rows), which the
model ignores.
**Open (modelling choices for Phu, none applied):** (1) a blue-side term; (2) regional rating drift
(see "Canonical names" known issue), since cross-region links are thin; (3) K and the half-life
(`k_scale` shrinks old games' K, so ratings may sit close to 1500). These belong to the sweeps
that are out of scope for this PR.
**K weighting:** with `k_scale`, games before `cutoff_date` use decayed K but every game after it
uses full K. The backtest runs with cutoff = start_date, so this only matters if a cutoff earlier than
start_date is ever used.
**Revisit if:** Any of the above changes the pooled in_tournament log loss.

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

## 2026-10-24 — Data exclusions: a listed gameid is dropped, any other bad game raises
**Decision:** `config/data_exclusions.yaml` lists `{gameid, reason}`. `load_games` drops only those
gameids, before validation. `ingest_report` shows the excluded games it dropped and any listed gameid
not found in the loaded files. Seeded with `ESPORTSTMNT01_3408461` (LCK, Liiv SANDBOX vs T1,
2023-08-04) and `LOLTMNT01_52116` (ESLOL, 2024-02-08): both team rows have result 0 in source.
**Alternatives considered:** Auto-voiding any game without exactly one win (silent, would hide real
corruption); fixing the results by hand (the true winner is unknowable).
**Evidence:** Read-only profile of the 2023–2026 CSVs: 2025 and 2026 load cleanly; 2023 and 2024 each
fail on exactly one 0/0 game. `tests/test_ingest.py` (exclusion tests); `python -m worlds.ingest`
reports both dropped and none missing.
**Revisit if:** A future Oracle's Elixir download fixes these games (the report would list them as
not found, so the entry can be removed).

## 2026-10-24 — Dates are UTC; every leakage comparison uses the full timestamp
**Decision:** Oracle's Elixir dates are UTC, stored timezone-naive. All `date < t` comparisons use the
full timestamp, never the calendar date, and `cutoff_date` may be a full timestamp. Worlds 2026 is in
the US, so games start 17:00–20:00 UTC and run past midnight UTC.
**Alternatives considered:** Local tournament time (needs a per-event timezone table and gives
nothing the model needs); comparing calendar dates (a game at 00:30 UTC would count as the same
day as a cutoff the evening before).
**Evidence:** Checked against the 2023 Seoul, 2024 London and 2025 Chengdu finals start times.
`tests/test_ingest.py::test_game_after_midnight_utc_is_compared_by_timestamp`. No code in `src/`
truncates dates. For the backtest: YAML parses `start_date: 2023-10-10` as `datetime.date`, so
convert with `pd.Timestamp(...)` before comparing with the datetime64 column
(`tests/test_config.py` does this).
**Revisit if:** A source with local-time dates is added.

## 2026-10-24 — Canonical names are required only for international leagues and Worlds teams
**Decision:** The unknown-team stop in `main()` applies to (a) names appearing in a league listed in
`config/ingest.yaml` `international_leagues` and (b) teams in `config/worlds_<year>.yaml`. Every other
name passes through as its own team and `ingest_report` counts it (`other_teams`). This replaces the
PR #5 rule that every name must be canonical.
**Alternatives considered:** Canonical for all 1,113 names (most appear only in minor leagues and
never reach an international event); canonical for international events only (would miss a Worlds
team that has no international games).
**Evidence:** 1,113 distinct names across 2023–26, only 68 in the international leagues.
**Known issue (not fixed here):** An "international league label" is not the same as a "cross-region
game". WLDs includes regional qualifiers weeks before each main event, and EWC April–June 2026 is 50
teams playing mostly inside their own region. Future Elo work that treats international games as the
cross-region link must filter these first.
**Revisit if:** Elo regional drift shows up in the backtest.

## 2026-10-24 — International league list
**Decision:** `[WLDs, MSI, FST, EWC, ASI, DCGI]`. ASI (2025-10, main rosters from KR, CN, VN and
PCS) and DCGI (2026-10, main rosters from KR, CN, EU, NA, BR and VN) are added.
**Alternatives considered:** KeSPA Cup (mostly LCK teams, two NA guests), AC (NA vs BR inside one
region); the academy and minor-league mixes AM, ASCI, PCL, WSCI, CD, LRN and LRS (rejected: not
main rosters).
**Evidence:** Team-region mix per league, 2023–26 data (regions from each team's most-played major
league).
**Revisit if:** A league's role in cross-region strength is clearer on closer inspection.

## 2026-10-24 — Backtest start dates are the play-in start
**Decision:** `config/backtest.yaml` start_date: 2023-10-10, 2024-09-25, 2025-10-14. Earlier WLDs
games (27, 26 and 12 games) are qualifiers, kept as rating data and not evaluated.
**Alternatives considered:** Main-event start (leaves the play-in out of evaluation).
**Evidence:** invenglobal.com/articles/18339, lolesports.com/en-US/news/worlds-2024,
lolesports.com/en-US/news/worlds-2025-heads-to-china. `tests/test_real_data.py`: the first WLDs game
on or after each start_date falls on that UTC day, and earlier WLDs games exist in all three years.
Note: 2023-10-09 has three WLDs games, Golden Guardians 0–3 Team BDS (the on-site Worlds Qualifying
Series), which count as qualifier rating data.
**Revisit if:** Official dates are corrected.

## 2026-10-24 — Aliases: Team Liquid → Team Liquid Alienware; Team Secret stays separate (Team Secret part SUPERSEDED, see "Team Secret EWC rows are Team Secret Whales")
**Decision:** Alias `Team Liquid` → `Team Liquid Alienware` (canonical, and the name used in
`config/worlds_2026.yaml`). `Team Secret` is NOT aliased to `Team Secret Whales`. KeSPA Cup and AC stay
out of the international league list. `worlds_2026.yaml` `teams` holds the 16 Swiss Stage teams.
**Alternatives considered:** Keeping `Team Liquid` canonical (data name; rejected so the Worlds list
matches the official 2026 name). Aliasing Team Secret: it played VCS to 2024-08-10 and reappears only
in EWC 2026-05-20..07-15 against GAM, Karmine Corp and Sentinels, in weeks different from Team Secret
Whales' EWC games (05-05..05-14), so it looks like a name reuse by another roster.
**Evidence:** Per-name league and date ranges from the 2023–26 data. No other aliases applied; the
MAD Lions KOI → Movistar KOI, MGN Vikings Esports → MVK Esports, Fluxo → Fluxo W7M and Team Whales →
Team Secret Whales candidates are still unanswered. NRG's 580-day gap is noted, not resolved.
**Revisit if:** The Team Liquid history before the rebrand should not carry over to the new name.

## 2026-10-24 — Four more aliases (Phu: yes)
**Decision:** `MAD Lions KOI` → `Movistar KOI`, `MGN Vikings Esports` → `MVK Esports`, `Fluxo` →
`Fluxo W7M`, `Team Whales` → `Team Secret Whales`. The three old names that were canonical are removed
from `canonical`; `tests/test_config.py` checks that no alias key is also canonical.
**Alternatives considered:** Leaving them split (each Worlds team would start 2025 with a fresh rating).
**Evidence:** Leagues and date ranges per name, no overlap for MGN/MVK (2025-10-04 → 2026-01-17),
Fluxo (2024-08-10 → 2025-01-26) and Team Whales (2024-08-17 → 2025-01-18).
**Known problem (open):** the `Movistar KOI` name already existed for a different Spanish-league team
(LVP SL 2023-01..2024-07, EM, IC; 158 team rows) that overlaps in time with MAD Lions KOI's LEC games
(2023-01..2024-08). The alias merges both histories into one Elo team. Options: a league-bounded or
date-bounded alias (needs code), or renaming the Spanish-league rows to their own team.
**Revisit if:** the Movistar KOI backtest ratings look contaminated.

## 2026-10-24 — Movistar KOI collision resolved with a league-bounded alias
**Decision:** `config/team_aliases.yaml` gets an optional `league_aliases` list. `load_games` applies it
before the plain aliases: `Movistar KOI` on rows from LVP SL, EM or IC becomes `Movistar KOI (Spain)`
(an ordinary pass-through team). `MAD Lions KOI` → `Movistar KOI` then merges only the LEC lineage.
**Alternatives considered:** Date-bounded alias (the Spanish team's games all end before 2025-01-18,
but a date rule is fragile if a later file adds games); leaving the merge (contaminates the Worlds
team's rating).
**Evidence:** After ingest, `Movistar KOI` is LEC/MSI/WLDs/EWC only (2023-01-21..2026-10-23) and
`Movistar KOI (Spain)` is EM/IC/LVP SL only (2023-01-16..2024-11-05). Tests: `tests/test_ingest.py`
(league alias cases), `tests/test_config.py`.
**Revisit if:** The Spanish-league team plays in another league label, or the name `Movistar KOI` appears
in LVP SL/EM/IC after the 2025 rebrand.

## 2026-10-24 — Team Secret EWC rows are Team Secret Whales (supersedes the Team Secret part above)
**Decision (Phu):** League-bounded alias in `league_aliases`: EWC `Team Secret` → `Team Secret Whales`.
VCS 2023–24 `Team Secret` (147 games) stays a separate pass-through team and is no longer in `canonical`.
**Alternatives considered:** Keeping them separate (the earlier decision, judged on dates only); a plain alias
(would merge the unrelated VCS team).
**Evidence:** Playername overlap in data/raw: the 8 EWC `Team Secret` games (2026-05-20..07-15) were played by
Bie, Dire, Eddie, Hizto, Pun, the same five as Team Secret Whales in EWC, FST and MSI 2026 (LCP adds Hiro02).
Tests: `tests/test_ingest.py` (EWC → TSW, VCS untouched), `tests/test_config.py` (the target-collision test now
allows only merges listed in `MERGES`).
**Revisit if:** A non-EWC league also uses the name `Team Secret` for this roster.

## 2026-10-24 — KeSPA Cup excluded (academy rosters under main-team names)
**Decision (Phu):** `config/ingest.yaml` `excluded_leagues: [KeSPA Cup]`. `load_games` drops those games and
`python -m worlds.ingest` reports the count per league: 49 (2024-11-30..12-08), 56 (2025-12-06..12-14), 61
(2026-07-20..08-18), 166 total; none in 2023. In 2026, T1, Gen.G, Hanwha Life, Dplus Kia and KT Rolster
fielded academy players (e.g. T1: Cloud, Cypher, Guti, Haetae, Painter).
**Alternatives considered:** Renaming rows to separate "(KeSPA)" teams (opponents are mixed rosters too, so it
adds noise); keeping them (contaminates the main teams' Elo right before Worlds).
**Evidence:** Playername vs. the team's usual roster that quarter (modal team per player). Backtest effect not
measured yet; only the 2024 edition precedes a backtest Worlds (2025), so 2023–25 log loss should barely move
and the effect is mostly on 2026 ratings.
**Revisit if:** The backtest shows the exclusion changes log loss (compare with and without).

## 2026-10-24 — Stale exclusions raise
**Decision (Phu, PR #8 open item 1, option a):** A gameid in `data_exclusions.yaml` is dropped only if it still
fails validation. If it now validates, `load_games` raises ValueError naming the gameid ("exclusion no longer
needed, remove it from data_exclusions.yaml").
**Alternatives considered:** Keeping the silent drop (would hide a source fix and discard a good game).
**Evidence:** `tests/test_ingest.py` (still-broken game dropped, fixed game raises).

## 2026-10-24 — CDF (Coupe de France) excluded too
**Decision (Phu):** `excluded_leagues: [KeSPA Cup, CDF]`. In CDF 2023 Team BDS (2 games, 2023-09-28) and
Karmine Corp (3 games, 2023-09-29..10-04) fielded academy rosters under the main names, right before Worlds 2023.
**Alternatives considered:** Excluding only the 5 flagged games (needs a gameid list that skips validation;
a second mechanism for 5 games).
**Evidence:** Playername vs. each team's usual roster that quarter. The whole league drops 141 games (72 in
2023, 69 in 2024), including 4 unflagged Karmine Corp and 18 Solary games.
**Revisit if:** The backtest shows the exclusion changes log loss.


## 2026-10-26 — Report pre-start WLDs games
**Decision (Phu, PR #11 leakage review Low, option 1):** `backtest_worlds` returns `n_prestart_wlds` (WLDs games in
`year` with `date < start_date`) and `python -m worlds.backtest` prints one line per year. Counts: 2023 = 27,
2024 = 26, 2025 = 12. Reporting only: no prediction or log-loss change.
**Why `start_date` stays:** The 2023 games just before 2023-10-10 are the Worlds Qualifying Series (GG 3–0 BDS,
2023-10-09, LoL Park), a qualifier. The 2024 and 2025 pre-start games end 11 and 17 days before play-ins, so they are
regional qualifiers. All stay rating data, not scored.
**Source:** https://www.esports.net/news/lol/lol-worlds-qualifying-series/
