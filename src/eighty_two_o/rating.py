"""Rate a drafted team: how many points per 100 possessions better than an average team it is.

The rating starts from each player's Box Plus/Minus, which is computed purely from box-score
stats and measured against the league average of the player's own season, so players from
different eras are comparable. It then judges how the eight players fit together: whether
there is only one ball for too many scorers, enough playmaking and rebounding, and whether
the starters cover the five positions. The result is on the same scale as a real team's net
rating, so it can be compared directly with the historical opponents.
"""

import itertools
import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from eighty_two_o.config import DEFAULT_RATING, RatingConfig
from eighty_two_o.data.models import PlayerSeason

STARTERS = 5
BENCH = 3


class TeamRating(BaseModel):
    """A team's rating and the parts it is made of (all in points per 100 possessions)."""

    model_config = ConfigDict(frozen=True)

    net: float
    """The final rating, after saturation."""
    pre_cap: float
    """The sum of the components below, before saturation."""
    talent: float
    """Box-score value of the eight players, after shot sharing, special cards included."""
    card_boost: float
    """How much of ``talent`` comes from special cards."""
    talent_unshared: float
    """``talent`` as if there were no shot-sharing penalty."""
    shot_sharing: float
    """``talent - talent_unshared``: zero or negative."""
    under_usage: float
    playmaking: float
    rebounding: float
    position_fit: float
    usage_total: float
    assist_total: float
    rebound_total: float


def player_value(
    player: PlayerSeason, config: RatingConfig = DEFAULT_RATING
) -> tuple[float, float]:
    """Estimate a player's offensive and defensive value per 100 possessions.

    Box Plus/Minus is noisy over few minutes, so seasons shorter than
    ``config.full_trust_minutes`` are pulled toward ``config.value_prior``. A special card's
    boost is then added, half to offence and half to defence.

    Args:
        player: The card.
        config: Rating constants.

    Returns:
        The ``(offence, defence)`` values.
    """
    trust = min(1.0, player.minutes_total / config.full_trust_minutes)
    offence = config.value_prior + (player.obpm - config.value_prior) * trust
    defence = config.value_prior + (player.dbpm - config.value_prior) * trust
    boost = config.card_boosts.get(player.card_id, 0.0)
    return offence + boost / 2, defence + boost / 2


def threshold_adjustment(
    total: float, baseline: float, shortfall_slope: float, bonus_slope: float, bonus_cap: float
) -> float:
    """Penalise a team total below its baseline and reward one above it, up to a cap.

    Args:
        total: The team's minute-weighted total.
        baseline: What a typical team has.
        shortfall_slope: Penalty per point below the baseline.
        bonus_slope: Bonus per point above the baseline.
        bonus_cap: The largest possible bonus.

    Returns:
        The adjustment: negative below the baseline, zero at it, positive above it.
    """
    shortfall = -shortfall_slope * max(0.0, baseline - total)
    bonus = min(bonus_cap, bonus_slope * max(0.0, total - baseline))
    return shortfall + bonus


def position_cost(starters: Sequence[PlayerSeason], config: RatingConfig = DEFAULT_RATING) -> float:
    """Find the cheapest way to slot the starters into PG, SG, SF, PF and C.

    Args:
        starters: The five starters.
        config: Rating constants (``position_costs``).

    Returns:
        The total cost of the best assignment; zero when every starter plays his own position.
    """
    return min(
        sum(
            config.position_costs[abs(player.position - slot)]
            for player, slot in zip(starters, slots, strict=True)
        )
        for slots in itertools.permutations(range(len(starters)))
    )


def rate_team(
    starters: Sequence[PlayerSeason],
    bench: Sequence[PlayerSeason],
    config: RatingConfig = DEFAULT_RATING,
) -> TeamRating:
    """Rate a lineup of five starters and three bench players.

    Args:
        starters: The five starters (34 minutes each).
        bench: The three bench players (sharing the other 70 minutes).
        config: Rating constants.

    Returns:
        The rating and its breakdown.

    Raises:
        ValueError: If there are not exactly 5 starters and 3 bench players.
    """
    if len(starters) != STARTERS or len(bench) != BENCH:
        raise ValueError(f"need {STARTERS} starters and {BENCH} bench players")

    weighted = [(config.starter_minutes / 48, p) for p in starters]
    weighted += [(config.bench_minutes / 48, p) for p in bench]

    usage_total = sum(w * p.usage for w, p in weighted)
    assist_total = sum(w * p.assist_pct for w, p in weighted)
    rebound_total = sum(w * p.rebound_pct for w, p in weighted)
    share = min(1.0, config.usage_baseline / usage_total) ** config.usage_exponent

    unboosted = config.model_copy(update={"card_boosts": {}})

    def talent_with(share: float, rating_config: RatingConfig) -> float:
        offence = 0.0
        defence = 0.0
        for weight, player in weighted:
            off, dfn = player_value(player, rating_config)
            offence += weight * (off * share if off > 0 else off)
            defence += weight * dfn
        return config.talent_offset + config.talent_scale * (offence + defence)

    talent = talent_with(share, config)
    talent_unshared = talent_with(1.0, config)
    card_boost = talent - talent_with(share, unboosted)

    under_usage = -config.under_usage_slope * max(0.0, config.under_usage_floor - usage_total)
    playmaking = threshold_adjustment(
        assist_total,
        config.playmaking_baseline,
        config.playmaking_shortfall_slope,
        config.playmaking_bonus_slope,
        config.playmaking_bonus_cap,
    )
    rebounding = threshold_adjustment(
        rebound_total,
        config.rebounding_baseline,
        config.rebounding_shortfall_slope,
        config.rebounding_bonus_slope,
        config.rebounding_bonus_cap,
    )
    position_fit = -position_cost(starters, config)

    pre_cap = talent + under_usage + playmaking + rebounding + position_fit
    return TeamRating(
        net=config.cap * math.tanh(pre_cap / config.cap),
        pre_cap=pre_cap,
        talent=talent,
        card_boost=card_boost,
        talent_unshared=talent_unshared,
        shot_sharing=talent - talent_unshared,
        under_usage=under_usage,
        playmaking=playmaking,
        rebounding=rebounding,
        position_fit=position_fit,
        usage_total=usage_total,
        assist_total=assist_total,
        rebound_total=rebound_total,
    )
