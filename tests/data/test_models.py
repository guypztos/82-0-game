import pydantic
import pytest

from eighty_two_o.data.models import PlayerSeason, Position, TeamSeason, format_season
from tests.factories import make_player, make_team


@pytest.mark.parametrize(
    ("season", "label"), [(2016, "2015-16"), (2000, "1999-00"), (1980, "1979-80")]
)
def test_format_season(season: int, label: str) -> None:
    assert format_season(season) == label


def test_position_distance_is_the_value_difference() -> None:
    assert abs(Position.PG - Position.C) == 4
    assert abs(Position.SF - Position.PF) == 1


def test_player_season_properties() -> None:
    player = make_player(
        player_id="curryst01", season=2016, team="GSW", games=79, minutes_total=2700
    )

    assert player.card_id == "curryst01:2016:GSW"
    assert player.team_key == "GSW:2016"
    assert player.season_label == "2015-16"
    assert player.minutes == pytest.approx(2700 / 79)


def test_team_season_properties() -> None:
    team = make_team(team="GSW", season=2016, name="Golden State Warriors", wins=73, losses=9)

    assert team.key == "GSW:2016"
    assert team.label == "2015-16 Golden State Warriors"
    assert team.record == "73-9"


def test_records_are_frozen() -> None:
    player = make_player()

    with pytest.raises(pydantic.ValidationError):
        player.name = "Someone Else"  # type: ignore[misc]


def test_records_round_trip_through_json() -> None:
    player = make_player(position=Position.C)
    team = make_team()

    assert PlayerSeason.model_validate_json(player.model_dump_json()) == player
    assert TeamSeason.model_validate_json(team.model_dump_json()) == team
