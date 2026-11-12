# Worlds 2026 pre-quarterfinal sensitivity check: game1_coin_flip

Robustness check only. Primary prediction unchanged; it is the one reported.
Same pre-cutoff data, ratings, H, q, sigma, n_runs and seed; only the override differs.

- commit: `64171d4a451dc79d5dc728fbb85260d74ed14bca`
- dirty_worktree: `False`
- config_sha256: `fe2d60dbbfedd6818f9d84517aa915e81e847b83465ca3ed228126f0a06cbd23`
- prediction_cutoff_utc: `2026-11-02T00:00:00`
- last_swiss_game_utc: `2026-10-31 23:05:06`
- n_gap_games_ignored: `9`
- last_game_used_utc: `2026-11-01 11:42:53`
- data_sha256: `3281b29ad7fc7f463b3499e47135f07efdfd57819ae2b7a18223f349110f8122`
- csv_snapshot: `{'file': '2026_LoL_esports_match_data_from_OraclesElixir.csv', 'covers_post_cutoff_rows': True, 'sha256': 'baea09cf7a1854bc817be2802e494ec0f04b437b442c3993e442e082aa72ed9e', 'modified': '2026-11-11T23:44:22.815716028'}`
- H: `23.309278175100058`
- q: `0.21831797235023043`
- n_q: `1736`
- sigma: `50`
- n_runs: `10000`
- seed: `42`
- variant: `game1_coin_flip`
- override: `{'file': 'config/sensitivity/game1_coin_flip.yaml', 'sha256': 'de6cb4230dc6453d81902e17b8f86b518b859b7eb84229fb278d835aa97be13d', 'content': {'rofs_game1': {'quarterfinals': 'coin_flip'}}}`
- data_hash_matches_primary: `True`
- compared_to: `{'file': 'results/worlds_2026_preQF.json', 'tag': 'pred-2026-preQF', 'commit': '1efe4e7d7d3497563eede2bc297f528fe3ca3584', 'config_sha256': 'fe2d60dbbfedd6818f9d84517aa915e81e847b83465ca3ed228126f0a06cbd23'}`
- model: `{'k_factor': 32, 'decay_half_life_days': 182, 'side_advantage': 'pre_cutoff_rate', 'league_offsets': 'on', 'k_league': 64}`

| team | P(SF) primary | variant | diff | P(final) primary | variant | diff | P(title) primary | variant | diff |
|---|---|---|---|---|---|---|---|---|---|
| Gen.G | 0.957 | 0.958 | +0.001 | 0.767 | 0.768 | +0.001 | 0.550 | 0.550 | +0.000 |
| Bilibili Gaming | 0.636 | 0.631 | -0.005 | 0.459 | 0.455 | -0.004 | 0.194 | 0.192 | -0.002 |
| T1 | 0.860 | 0.863 | +0.003 | 0.295 | 0.296 | +0.001 | 0.082 | 0.083 | +0.000 |
| Dplus Kia | 0.364 | 0.369 | +0.005 | 0.232 | 0.235 | +0.003 | 0.074 | 0.076 | +0.002 |
| Invictus Gaming | 0.504 | 0.504 | +0.000 | 0.106 | 0.105 | -0.000 | 0.048 | 0.048 | -0.000 |
| Top Esports | 0.496 | 0.496 | +0.000 | 0.117 | 0.117 | -0.000 | 0.048 | 0.048 | +0.000 |
| LYON | 0.043 | 0.042 | -0.001 | 0.010 | 0.010 | -0.000 | 0.002 | 0.002 | +0.000 |
| Karmine Corp | 0.140 | 0.137 | -0.003 | 0.014 | 0.014 | -0.000 | 0.002 | 0.002 | +0.000 |

Quarterfinal series, P(first team wins), averaged over the rating noise:

| series | primary | variant | diff |
|---|---|---|---|
| Dplus Kia v Bilibili Gaming | 0.369 | 0.375 | +0.006 |
| Karmine Corp v T1 | 0.142 | 0.139 | -0.003 |
| Top Esports v Invictus Gaming | 0.499 | 0.499 | +0.000 |
| Gen.G v LYON | 0.956 | 0.957 | +0.001 |

Max |change| in title odds: 0.002
