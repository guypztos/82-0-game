import math
import statistics

import pytest

from eighty_two_o.config import DEFAULT_RATING, RatingConfig
from eighty_two_o.data.models import PlayerSeason, Position
from eighty_two_o.data.repository import Dataset
from eighty_two_o.rating import (
    TeamRating,
    player_value,
    position_cost,
    rate_team,
    threshold_adjustment,
)
from tests.factories import make_player

ALL_TIME = (
    ("curryst01:2016:GSW", "jordami01:1991:CHI", "jamesle01:2013:MIA", "duncati01:2003:SAS",
     "onealsh01:2000:LAL"),
    ("johnsma02:1987:LAL", "birdla01:1986:BOS", "olajuha01:1994:HOU"),
)  # fmt: skip
FIVE_CENTRES = (
    ("onealsh01:2000:LAL", "olajuha01:1994:HOU", "robinda01:1994:SAS", "ewingpa01:1990:NYK",
     "jokicni01:2022:DEN"),
    ("johnsma02:1987:LAL", "birdla01:1986:BOS", "curryst01:2016:GSW"),
)  # fmt: skip
FIVE_SCORERS = (
    ("jordami01:1987:CHI", "bryanko01:2006:LAL", "hardeja01:2019:HOU", "iversal01:2001:PHI",
     "westbru01:2017:OKC"),
    ("duranke01:2014:OKC", "mcgratr01:2003:ORL", "wadedw01:2009:MIA"),
)  # fmt: skip
AVDIJA = "avdijde01:2026:POR"
NO_BOOSTS = RatingConfig(card_boosts={})


def rate_ids(dataset: Dataset, lineup: tuple[tuple[str, ...], tuple[str, ...]]) -> TeamRating:
    starters, bench = lineup
    return rate_team([dataset.card(c) for c in starters], [dataset.card(c) for c in bench])


def rate_top_eight(
    dataset: Dataset, team_key: str, config: RatingConfig = DEFAULT_RATING
) -> TeamRating:
    roster = dataset.roster(team_key)
    return rate_team(roster[:5], roster[5:8], config)


def five(position: Position = Position.SF, **fields: object) -> list[PlayerSeason]:
    return [make_player(player_id=f"s{i}", position=position, **fields) for i in range(5)]


def three(**fields: object) -> list[PlayerSeason]:
    return [make_player(player_id=f"b{i}", **fields) for i in range(3)]


def balanced_five(**fields: object) -> list[PlayerSeason]:
    return [make_player(player_id=f"s{i}", position=Position(i), **fields) for i in range(5)]


class TestPlayerValue:
    def test_full_minutes_use_bpm_as_is(self) -> None:
        player = make_player(minutes_total=2000, obpm=5.0, dbpm=-2.0)

        assert player_value(player) == pytest.approx((5.0, -2.0))

    def test_small_minutes_are_pulled_toward_the_prior(self) -> None:
        player = make_player(minutes_total=600, obpm=5.0, dbpm=-3.0)

        # half trust: halfway between -1 and the real value
        assert player_value(player) == pytest.approx((2.0, -2.0))

    def test_special_card_boost_is_split_between_offence_and_defence(self) -> None:
        player = make_player(minutes_total=2000, obpm=1.0, dbpm=0.0)
        config = RatingConfig(card_boosts={player.card_id: 4.0})

        assert player_value(player, config) == pytest.approx((3.0, 2.0))

    def test_avdija_2026_is_the_default_special_card(self, dataset: Dataset) -> None:
        avdija = dataset.card(AVDIJA)

        boosted = player_value(avdija)
        plain = player_value(avdija, NO_BOOSTS)

        assert boosted[0] - plain[0] == pytest.approx(3.0)
        assert boosted[1] - plain[1] == pytest.approx(3.0)
        assert sum(boosted) == pytest.approx(10.3)

    def test_other_avdija_seasons_are_not_boosted(self, dataset: Dataset) -> None:
        avdija_2025 = dataset.card("avdijde01:2025:POR")

        assert player_value(avdija_2025) == player_value(avdija_2025, NO_BOOSTS)


class TestThresholdAdjustment:
    def test_shortfall_is_linear(self) -> None:
        assert threshold_adjustment(70, 77, 0.15, 0.05, 1.5) == pytest.approx(-1.05)

    def test_at_the_baseline_there_is_no_adjustment(self) -> None:
        assert threshold_adjustment(77, 77, 0.15, 0.05, 1.5) == 0

    def test_bonus_is_linear_then_capped(self) -> None:
        assert threshold_adjustment(87, 77, 0.15, 0.05, 1.5) == pytest.approx(0.5)
        assert threshold_adjustment(200, 77, 0.15, 0.05, 1.5) == pytest.approx(1.5)


class TestPositionCost:
    def test_perfectly_slotted_five_costs_nothing(self) -> None:
        assert position_cost(list(reversed(balanced_five()))) == 0

    def test_five_centres(self) -> None:
        assert position_cost(five(Position.C)) == pytest.approx(10.0)

    def test_cost_grows_with_distance(self) -> None:
        two_point_guards = balanced_five()
        two_point_guards[1] = make_player(position=Position.PG)

        assert position_cost(two_point_guards) == pytest.approx(0.5)


class TestRateTeam:
    @pytest.mark.parametrize(("starters", "bench"), [(4, 3), (5, 2), (6, 3)])
    def test_wrong_lineup_size_is_rejected(self, starters: int, bench: int) -> None:
        players = [make_player(player_id=f"p{i}") for i in range(starters + bench)]

        with pytest.raises(ValueError, match="5 starters and 3 bench"):
            rate_team(players[:starters], players[starters:])

    def test_weights_sum_to_five_players(self) -> None:
        rating = rate_team(balanced_five(usage=20.0), three(usage=20.0))

        assert rating.usage_total == pytest.approx(100.0)

    def test_average_team_is_near_zero(self) -> None:
        rating = rate_team(
            balanced_five(usage=20.0, assist_pct=15.4, rebound_pct=10.0),
            three(usage=20.0, assist_pct=15.4, rebound_pct=10.0),
        )

        assert rating.pre_cap == pytest.approx(-0.2)
        assert rating.net == pytest.approx(-0.2, abs=1e-4)
        assert rating.position_fit == 0
        assert rating.shot_sharing == 0
        assert rating.card_boost == 0

    def test_too_many_scorers_lowers_positive_offence(self) -> None:
        rating = rate_team(balanced_five(usage=35.0, obpm=6.0), three(usage=35.0, obpm=6.0))

        assert rating.shot_sharing < 0
        assert rating.talent < rating.talent_unshared

    def test_shot_sharing_does_not_improve_poor_offence(self) -> None:
        rating = rate_team(balanced_five(usage=35.0, obpm=-3.0), three(usage=35.0, obpm=-3.0))

        assert rating.shot_sharing == 0

    def test_nobody_to_carry_the_offence_is_penalised(self) -> None:
        rating = rate_team(balanced_five(usage=15.0), three(usage=15.0))

        assert rating.under_usage == pytest.approx(-0.15 * (96 - 75))

    def test_missing_playmaking_and_rebounding_are_penalised(self) -> None:
        rating = rate_team(
            balanced_five(assist_pct=5.0, rebound_pct=5.0),
            three(assist_pct=5.0, rebound_pct=5.0),
        )

        assert rating.playmaking == pytest.approx(-0.15 * (77 - 25))
        assert rating.rebounding == pytest.approx(-0.5 * (50 - 25))

    def test_components_add_up_to_pre_cap(self) -> None:
        rating = rate_team(five(Position.C, usage=30.0, obpm=4.0), three(assist_pct=40.0))

        parts = (
            rating.talent,
            rating.under_usage,
            rating.playmaking,
            rating.rebounding,
            rating.position_fit,
        )
        assert sum(parts) == pytest.approx(rating.pre_cap)
        assert rating.net == pytest.approx(32 * math.tanh(rating.pre_cap / 32))

    def test_net_is_monotonic_and_never_exceeds_the_cap(self) -> None:
        nets = [
            rate_team(balanced_five(obpm=bpm, dbpm=bpm), three(obpm=bpm, dbpm=bpm)).net
            for bpm in range(-10, 41, 5)
        ]

        assert nets == sorted(nets)
        assert all(abs(net) < 32 for net in nets)

    def test_special_card_raises_the_rating_by_its_boost(self) -> None:
        starters = balanced_five(obpm=2.0)
        config = RatingConfig(card_boosts={starters[0].card_id: 6.0})

        boosted = rate_team(starters, three(), config)
        plain = rate_team(starters, three(), NO_BOOSTS)

        assert boosted.card_boost == pytest.approx(0.856 * 6.0 * 34 / 48)
        assert boosted.talent - plain.talent == pytest.approx(boosted.card_boost)
        assert boosted.net > plain.net


class TestPinnedRealLineups:
    """Values measured when the constants were validated; see the build plan."""

    def test_all_time_lineup(self, dataset: Dataset) -> None:
        rating = rate_ids(dataset, ALL_TIME)

        assert rating.net == pytest.approx(26.96, abs=0.15)
        assert rating.position_fit == pytest.approx(-0.5)
        assert rating.playmaking == pytest.approx(1.5)
        assert rating.rebounding == pytest.approx(2.0)
        assert rating.usage_total == pytest.approx(150.4, abs=0.05)

    def test_five_centres(self, dataset: Dataset) -> None:
        rating = rate_ids(dataset, FIVE_CENTRES)

        assert rating.net == pytest.approx(23.08, abs=0.15)
        assert rating.position_fit == pytest.approx(-10.0)

    def test_five_scorers(self, dataset: Dataset) -> None:
        rating = rate_ids(dataset, FIVE_SCORERS)

        assert rating.net == pytest.approx(21.85, abs=0.15)
        assert rating.position_fit == pytest.approx(-5.5)
        assert rating.rebounding == pytest.approx(-1.42, abs=0.01)

    @pytest.mark.parametrize(
        ("team_key", "expected"), [("CHI:1996", 14.0), ("GSW:2016", 9.7), ("CHA:2012", -12.5)]
    )
    def test_real_top_eights(self, dataset: Dataset, team_key: str, expected: float) -> None:
        assert rate_top_eight(dataset, team_key).net == pytest.approx(expected, abs=0.15)

    def test_rating_tracks_every_real_team(self, dataset: Dataset) -> None:
        model = [rate_top_eight(dataset, team.key).net for team in dataset.team_seasons]
        real = [team.net_rating for team in dataset.team_seasons]

        assert statistics.correlation(model, real) >= 0.92
        assert statistics.fmean(abs(m - r) for m, r in zip(model, real, strict=True)) <= 1.7
        assert abs(statistics.fmean(model) - statistics.fmean(real)) <= 0.3

    def test_avdija_boost_on_his_real_team(self, dataset: Dataset) -> None:
        boosted = rate_top_eight(dataset, "POR:2026")
        plain = rate_top_eight(dataset, "POR:2026", NO_BOOSTS)

        assert boosted.card_boost > 3.0
        assert plain.card_boost == 0
        assert boosted.net > plain.net + 3.0
