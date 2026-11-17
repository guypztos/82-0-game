"""Every tunable number in the game, grouped by the part of the game that uses it."""

from pydantic import BaseModel, ConfigDict, Field


class DraftConfig(BaseModel):
    """Rules of the draft."""

    model_config = ConfigDict(frozen=True)

    rounds: int = 8
    """Players drafted: 5 starters and 3 bench players."""
    rerolls: int = 2
    """Rerolls available for the whole draft."""


DEFAULT_DRAFT = DraftConfig()


class RatingConfig(BaseModel):
    """Constants of the team rating, validated against every real team-season since 1980.

    See ``rating.py`` for how each one is used. Changing them changes how hard 82-0 is.
    """

    model_config = ConfigDict(frozen=True)

    starter_minutes: float = 34.0
    bench_minutes: float = 70 / 3
    value_prior: float = -1.0
    full_trust_minutes: float = 1200.0
    usage_baseline: float = 104.0
    usage_exponent: float = 0.5
    under_usage_floor: float = 96.0
    under_usage_slope: float = 0.15
    talent_offset: float = -0.2
    talent_scale: float = 0.856
    playmaking_baseline: float = 77.0
    playmaking_shortfall_slope: float = 0.15
    playmaking_bonus_slope: float = 0.05
    playmaking_bonus_cap: float = 1.5
    rebounding_baseline: float = 50.0
    rebounding_shortfall_slope: float = 0.5
    rebounding_bonus_slope: float = 0.25
    rebounding_bonus_cap: float = 2.0
    position_costs: tuple[float, float, float, float, float] = (0.0, 0.5, 1.5, 3.0, 5.0)
    """Cost of a starter playing 0, 1, 2, 3 or 4 steps from his position on PG-SG-SF-PF-C."""
    cap: float = 32.0
    card_boosts: dict[str, float] = Field(default_factory=lambda: {"avdijde01:2026:POR": 6.0})
    """Special cards: extra value per card id, split evenly between offence and defence."""


DEFAULT_RATING = RatingConfig()


class SimConfig(BaseModel):
    """Constants of the season simulation.

    With ``sigma = 10`` a +10 team (the real 73-9 Warriors) wins about 81% of its games, and a
    team needs about +21 to go 82-0 once in 30 seasons.
    """

    model_config = ConfigDict(frozen=True)

    games: int = 82
    sigma: float = 10.0
    """Standard deviation of a game's margin around its expected value, in points."""
    home_edge: float = 2.5
    total_points_mean: float = 212.0
    total_points_sd: float = 16.0
    total_points_min: int = 160
    total_points_max: int = 270
    loser_points_min: int = 70
    """Floor on the losing score so huge blowouts still look like basketball scores."""


DEFAULT_SIM = SimConfig()
