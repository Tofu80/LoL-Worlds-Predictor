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
