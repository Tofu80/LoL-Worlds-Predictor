import math
from dataclasses import dataclass, field

import pandas as pd

# Planned third option: Option B regress-to-mean (parked).
DECAY_METHODS = ("k_scale", "none")
SIDE_MODES = ("none", "pre_cutoff_rate")
LEAGUE_MODES = ("off", "on")


def decay_weight(age_days: float, half_life_days: float) -> float:
    """Exponential decay: 1 at age 0, halving every half_life_days."""
    return math.exp(-math.log(2) * age_days / half_life_days)


def expected_score(rating_a: float, rating_b: float, h: float = 0.0) -> float:
    """P(a wins). h is a bonus in Elo points added to a (the blue side)."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a - h) / 400))


def update_ratings(
    rating_a: float,
    rating_b: float,
    result: float,
    k: float,
    h: float = 0.0,
) -> tuple[float, float]:
    ea = expected_score(rating_a, rating_b, h)
    new_a = rating_a + k * (result - ea)
    new_b = rating_b + k * ((1 - result) - (1 - ea))
    return new_a, new_b


def blue_advantage(
    games: pd.DataFrame, cutoff_date: pd.Timestamp, window_days: float
) -> float:
    """H = 400*log10(r/(1-r)), r = blue win rate over [cutoff - window, cutoff), all leagues."""
    start = cutoff_date - pd.Timedelta(days=window_days)
    blue = games[
        (games["side"] == "Blue")
        & (games["date"] >= start)
        & (games["date"] < cutoff_date)
    ]
    if blue.empty:
        raise ValueError(f"no games in the {window_days} days before {cutoff_date}")
    r = float(blue["result"].mean())
    if not 0.0 < r < 1.0:
        raise ValueError(f"blue win rate {r} makes H infinite")
    return 400 * math.log10(r / (1 - r))


@dataclass
class EloState:
    """Team ratings plus optional league offsets: strength = team + league[member].

    With league offsets off (k_league None) `league` and `member` stay empty and
    strength is the team rating.
    """

    initial: float
    h: float = 0.0
    k_league: float | None = None
    international: frozenset = frozenset()
    lineage: dict = field(default_factory=dict)
    skip: frozenset = frozenset()
    inherit: dict = field(default_factory=dict)
    team: dict = field(default_factory=dict)
    league: dict = field(default_factory=dict)
    member: dict = field(default_factory=dict)
    # None = not recording. A list collects one row per team per update (see _record).
    history: list | None = None

    def key(self, code: str) -> str:
        return self.lineage.get(code, code)

    def strength(self, team: str) -> float:
        base = self.team.get(team, self.initial)
        key = self.member.get(team)
        return base if key is None else base + self.league.get(key, 0.0)

    def p_blue(self, blue: str, red: str) -> float:
        return expected_score(self.strength(blue), self.strength(red), self.h)

    def _snap(self, *teams: str) -> dict:
        """(team rating, league offset) per team, as strength() reads them."""
        return {
            t: (
                self.team.get(t, self.initial),
                self.league.get(self.member.get(t), 0.0),
            )
            for t in teams
        }

    def _record(self, blue, red, gameid, date, before, after) -> None:
        for team, opp in ((blue, red), (red, blue)):
            (rb, ob), (ra, oa) = before[team], after[team]
            self.history.append(
                {
                    "gameid": gameid,
                    "date": date,
                    "team": team,
                    "opponent": opp,
                    "rating_before": rb,
                    "rating_after": ra,
                    "offset_before": ob,
                    "offset_after": oa,
                }
            )

    def observe(self, blue: str, red: str, gameid=None, date=None) -> None:
        """Record a game without updating anything (frozen ratings)."""
        if self.history is not None:
            snap = self._snap(blue, red)
            self._record(blue, red, gameid, date, snap, snap)

    def update(
        self,
        blue: str,
        red: str,
        league_code: str,
        blue_won: bool,
        k: float,
        weight: float = 1.0,
        gameid=None,
        date=None,
    ) -> None:
        """Add one game. The team level always updates; the league level only for
        an international game between two different league keys. Both zero-sum.
        gameid and date are only used when history is recording."""
        if self.history is None:
            return self._apply(blue, red, league_code, blue_won, k, weight)
        before = self._snap(blue, red)
        self._apply(blue, red, league_code, blue_won, k, weight)
        self._record(blue, red, gameid, date, before, self._snap(blue, red))

    def _apply(self, blue, red, league_code, blue_won, k, weight) -> None:
        # Winner first, with h's sign flipped for a red win: bit-identical to the
        # pre-H update when h == 0.
        w, l, hw = (blue, red, self.h) if blue_won else (red, blue, -self.h)
        step = 1 - expected_score(self.strength(w), self.strength(l), hw)
        self.team[w] = self.team.get(w, self.initial) + k * weight * step
        self.team[l] = self.team.get(l, self.initial) - k * weight * step
        if self.k_league is None:
            return
        if league_code in self.international:
            kw, kl = self.member.get(w), self.member.get(l)
            if kw is not None and kl is not None and kw != kl:
                delta = self.k_league * weight * step
                self.league[kw] = self.league.get(kw, 0.0) + delta
                self.league[kl] = self.league.get(kl, 0.0) - delta
        elif league_code not in self.skip:
            key = self.key(league_code)
            if key in self.inherit and key not in self.league:
                src = self.inherit[key]
                self.league[key] = sum(
                    n * self.league.get(s, 0.0) for s, n in src.items()
                ) / sum(src.values())
            self.member[blue] = self.member[red] = key


def _check_games(games: pd.DataFrame) -> None:
    # Two rows with min 0 and max 1 means exactly one win and one loss.
    per_game = games.groupby("gameid")["result"].agg(["size", "min", "max"])
    ok = (per_game["size"] == 2) & (per_game["min"] == 0) & (per_game["max"] == 1)
    bad = per_game.index[~ok]
    if len(bad):
        raise ValueError(
            f"gameids without exactly two rows and one win: {list(bad[:10])}"
        )
    sides = games.groupby("gameid")["side"].agg(lambda x: sorted(x))
    bad_sides = sides.index[sides.map(lambda x: x != ["Blue", "Red"])]
    if len(bad_sides):
        raise ValueError(
            f"gameids without one Blue and one Red row: {list(bad_sides[:10])}"
        )


def replay(
    games: pd.DataFrame,
    cutoff_date: pd.Timestamp,
    config: dict,
    record: bool = False,
) -> EloState:
    """Replay games dated strictly before cutoff_date; return the rating state.

    config keys: k_factor, initial_rating, decay_half_life_days, decay_method,
    side_advantage (none | pre_cutoff_rate, window side_advantage_window_days),
    league_offsets (off | on, with k_league, league_lineage,
    league_membership_skip, league_inherit) and international_leagues.
    H is computed once from games before cutoff_date and stays fixed. Decay
    weights are measured from cutoff_date and also scale k_league.
    record=True fills state.history with one row per team per game (rating and league
    offset before and after); it changes no rating.
    games needs gameid, date, teamname, side, result, plus league when offsets are on.
    """
    method = config["decay_method"]
    if method not in DECAY_METHODS:
        raise ValueError(f"decay_method must be one of {DECAY_METHODS}, got {method!r}")
    side = config.get("side_advantage", "none")
    if side not in SIDE_MODES:
        raise ValueError(f"side_advantage must be one of {SIDE_MODES}, got {side!r}")
    offsets = config.get("league_offsets", "off")
    if offsets not in LEAGUE_MODES:
        raise ValueError(
            f"league_offsets must be one of {LEAGUE_MODES}, got {offsets!r}"
        )
    _check_games(games)

    h = 0.0
    if side == "pre_cutoff_rate":
        h = blue_advantage(
            games, cutoff_date, config.get("side_advantage_window_days", 365)
        )
    state = EloState(
        initial=float(config["initial_rating"]),
        h=h,
        k_league=float(config["k_league"]) if offsets == "on" else None,
        international=frozenset(config.get("international_leagues", ())),
        lineage=dict(config.get("league_lineage", {})),
        skip=frozenset(config.get("league_membership_skip", ())),
        inherit=dict(config.get("league_inherit", {})),
        history=[] if record else None,
    )
    past = games[games["date"] < cutoff_date]
    cols = ["gameid", "date", "teamname", "result"]
    if offsets == "on":
        cols.append("league")
    blue = past.loc[past["side"] == "Blue", cols]
    red = past.loc[past["side"] == "Red", ["gameid", "teamname"]]
    pairs = blue.merge(red, on="gameid", suffixes=("_b", "_r")).sort_values(
        ["date", "gameid"]
    )
    for g in pairs.itertuples(index=False):
        weight = 1.0
        if method == "k_scale":
            age_days = (cutoff_date - g.date) / pd.Timedelta(days=1)
            weight = decay_weight(age_days, config["decay_half_life_days"])
        state.update(
            g.teamname_b,
            g.teamname_r,
            getattr(g, "league", ""),
            bool(g.result == 1),
            config["k_factor"],
            weight,
            g.gameid,
            g.date,
        )
    return state


def compute_ratings(
    games: pd.DataFrame,
    cutoff_date: pd.Timestamp,
    k: float,
    initial_rating: float,
    decay_half_life_days: float,
    decay_method: str,
) -> dict[str, float]:
    """Replay games dated strictly before cutoff_date; return {teamname: rating}.

    Plain team Elo (no side bonus, no league offsets; see replay for those).
    decay_method:
      k_scale: each game's K is multiplied by decay_weight(age_days, half-life),
               age_days = (cutoff_date - game date) in fractional days, measured
               from cutoff_date, not from today or from each later game.
      none:    weight 1 (plain Elo), the no-decay baseline.
    Both teams use the same scaled K, so every update is zero-sum. Games on or
    after cutoff_date are ignored; the backtest adds in-tournament games itself
    at full K (age 0).

    Raises ValueError for an unknown decay_method, or if any gameid in games
    (before or after the cutoff) doesn't have exactly two rows with one win.
    """
    return replay(
        games,
        cutoff_date,
        {
            "k_factor": k,
            "initial_rating": initial_rating,
            "decay_half_life_days": decay_half_life_days,
            "decay_method": decay_method,
        },
    ).team
