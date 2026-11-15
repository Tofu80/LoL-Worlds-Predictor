# Worlds 2026 pre-quarterfinal prediction: score

**n = 7 series, 25 games, 24 round items (1 series with odds).** This is far too little to say anything about model quality.

- tag: `pred-2026-preQF` (commit `1efe4e7d7d3497563eede2bc297f528fe3ca3584`)
- prediction: `results/worlds_2026_preQF.json`, config_sha256 `fe2d60dbbfedd6818f9d84517aa915e81e847b83465ca3ed228126f0a06cbd23`, data_sha256 `3281b29ad7fc7f463b3499e47135f07efdfd57819ae2b7a18223f349110f8122`
- results file: `config/worlds_2026_results.yaml`, sha256 `a06c33001b894db17be0e7aff6290482eb9b856fe36f08317fa1421a07f4083c`
- ratings frozen at the cutoff; probabilities averaged over the rating noise (sigma 50, 41-node Gauss-Hermite), conditional on the matchup happening.
- for SF and final matchups this ignores that the sim's advancing teams tended to have positive noise.
- baselines: half = 0.5 everywhere (round level: every series 0.5); blue_only = equal strengths, only the blue bonus H.
- results vs the CSV: {'QF1': 'verified', 'QF2': 'verified', 'QF3': 'verified', 'QF4': 'verified', 'SF1': 'verified', 'SF2': 'verified', 'F': 'verified'}

## Series (P that the first-listed team wins)

| series | A | B | P(A) model | P(A) blue-only | winner | score |
|---|---|---|---|---|---|---|
| QF1 | Dplus Kia | Bilibili Gaming | 0.369 | 0.493 | Bilibili Gaming | 3-0 |
| QF2 | Karmine Corp | T1 | 0.142 | 0.507 | T1 | 3-1 |
| QF3 | Top Esports | Invictus Gaming | 0.499 | 0.500 | Invictus Gaming | 3-1 |
| QF4 | Gen.G | LYON | 0.956 | 0.493 | Gen.G | 3-0 |
| SF1 | Bilibili Gaming | T1 | 0.684 | 0.500 | Bilibili Gaming | 3-1 |
| SF2 | Invictus Gaming | Gen.G | 0.182 | 0.500 | Gen.G | 3-0 |
| F | Bilibili Gaming | Gen.G | 0.331 | 0.500 | Bilibili Gaming | 3-1 |

| | log loss | Brier |
|---|---|---|
| model | 0.434 | 0.141 |
| half | 0.693 | 0.250 |
| blue_only | 0.695 | 0.251 |

## Rounds (8 teams each)

| round | model LL | half LL | blue-only LL | model Brier | half Brier | blue-only Brier |
|---|---|---|---|---|---|---|
| semifinal | 0.333 | 0.693 | 0.697 | 0.100 | 0.250 | 0.252 |
| final | 0.240 | 0.562 | 0.562 | 0.064 | 0.188 | 0.188 |
| title | 0.338 | 0.377 | 0.375 | 0.121 | 0.109 | 0.109 |

## Games (n = 25, log loss with bootstrap 95% CI)

| | log loss | 95% CI | Brier |
|---|---|---|---|
| model | 0.553 | [0.446, 0.663] | 0.186 |
| half | 0.693 | [0.693, 0.693] | 0.250 |
| blue_only | 0.682 | [0.655, 0.709] | 0.244 |

model minus blue-only: -0.129 [-0.232, -0.016] (negative = model better)

## Odds

n = 1 series. Margin removed by normalising. Snapshot = latest before the series start; later series' odds know earlier results, the frozen model does not.

log loss: bookmaker 0.935, model 1.106, half 0.693

| series | bookmaker | snapshot (UTC) | P(A) bookmaker | P(A) model | A won |
|---|---|---|---|---|---|
| F | TAB | 2026-11-14 14:02:53 | 0.393 | 0.331 | 1 |
