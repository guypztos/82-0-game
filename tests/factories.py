"""Small hand-built records for unit tests that should not depend on the real dataset."""

from eighty_two_o.data.models import PlayerSeason, Position, TeamSeason
from eighty_two_o.data.repository import Dataset
from eighty_two_o.sweep.models import CarSeason, DriverSeason
from eighty_two_o.sweep.repository import SweepDataset


def make_player(**overrides: object) -> PlayerSeason:
    """Build a card with sensible defaults; pass fields to override them."""
    fields: dict[str, object] = {
        "player_id": "testpl01",
        "name": "Test Player",
        "season": 2016,
        "team": "TST",
        "position": Position.SF,
        "age": 27,
        "games": 80,
        "minutes_total": 2400,
        "points": 15.0,
        "rebounds": 5.0,
        "assists": 3.0,
        "steals": 1.0,
        "blocks": 0.5,
        "turnovers": 2.0,
        "true_shooting": 0.56,
        "usage": 20.0,
        "assist_pct": 15.0,
        "rebound_pct": 10.0,
        "obpm": 0.0,
        "dbpm": 0.0,
    }
    fields.update(overrides)
    return PlayerSeason.model_validate(fields)


def make_team(**overrides: object) -> TeamSeason:
    """Build a team-season with sensible defaults; pass fields to override them."""
    fields: dict[str, object] = {
        "team": "TST",
        "season": 2016,
        "name": "Test Team",
        "wins": 41,
        "losses": 41,
        "net_rating": 0.0,
    }
    fields.update(overrides)
    return TeamSeason.model_validate(fields)


def make_dataset(team_count: int = 12, roster_size: int = 10) -> Dataset:
    """Build a small dataset: ``team_count`` teams in 2016, each with its own roster.

    Team ``i`` has abbreviation ``T{i:02d}`` and net rating ``i - team_count / 2``. Player ``j``
    of team ``i`` has id ``p{i:02d}{j:02d}``, plays ``3000 - 100 * j`` minutes, and the last
    player of every team is also on team 0's roster in 2015 under the same player id, so tests
    can exercise the one-person-per-draft rule.
    """
    teams = [
        make_team(team=f"T{i:02d}", name=f"Team {i}", net_rating=i - team_count / 2)
        for i in range(team_count)
    ]
    teams.append(make_team(team="T00", season=2015, name="Team 0"))
    players = [
        make_player(
            player_id=f"p{i:02d}{j:02d}",
            name=f"Player {i}-{j}",
            team=f"T{i:02d}",
            position=Position(j % 5),
            minutes_total=3000 - 100 * j,
        )
        for i in range(team_count)
        for j in range(roster_size)
    ]
    players.extend(
        make_player(
            player_id=f"p{i:02d}{roster_size - 1:02d}",
            name=f"Player {i}-{roster_size - 1}",
            team="T00",
            season=2015,
            minutes_total=500 + i,
        )
        for i in range(team_count)
    )
    return Dataset(players, teams)


def make_car(**overrides: object) -> CarSeason:
    """Build a constructor-season with sensible defaults; pass fields to override them."""
    fields: dict[str, object] = {
        "constructor_id": "test",
        "year": 2000,
        "name": "Test",
        "chassis_name": "T1",
        "engine_id": "testeng",
        "engine_name": "Testeng",
        "engine_badge": "Testeng",
        "car": 0.0,
        "engine": 0.0,
        "chassis": 0.0,
        "pit": 0.0,
        "pit_rated": True,
        "pit_rank": 1,
        "reliability": 1.0,
        "races": 16,
        "starts": 32,
        "wins": 1,
        "poles": 1,
        "podiums": 2,
        "mechanical_retirements": 4,
        "engine_wins": 1,
        "engine_teams": 1,
        "championship_position": 1,
        "rollable": True,
    }
    fields.update(overrides)
    return CarSeason.model_validate(fields)


def make_driver(**overrides: object) -> DriverSeason:
    """Build a driver card with sensible defaults; pass fields to override them."""
    fields: dict[str, object] = {
        "driver_id": "test-driver",
        "name": "Test Driver",
        "year": 2000,
        "constructor_id": "test",
        "rating": 0.0,
        "incident": 1.0,
        "starts": 16,
        "wins": 0,
        "poles": 0,
        "podiums": 0,
        "championship_position": 10,
        "main": True,
    }
    fields.update(overrides)
    return DriverSeason.model_validate(fields)


def make_sweep_dataset(
    years: tuple[int, ...] = (2000, 2001), cars_per_year: int = 4, drivers_per_car: int = 2
) -> SweepDataset:
    """Build a small Clean Sweep dataset.

    Car ``i`` of year ``y`` is constructor ``c{i}`` with strength ``i - cars_per_year / 2`` (all
    of it in the chassis) and is rollable. Its drivers are ``d{i}{j}-{y}`` (a different person
    every season) with rating ``-j``; the first two are its main drivers.
    """
    cars: list[CarSeason] = []
    drivers: list[DriverSeason] = []
    for year in years:
        for i in range(cars_per_year):
            strength = i - cars_per_year / 2
            cars.append(
                make_car(
                    constructor_id=f"c{i}",
                    year=year,
                    name=f"Team {i}",
                    car=strength,
                    chassis=strength,
                    engine_id=f"e{i}",
                    engine_name=f"Engine {i}",
                    engine_badge=f"Engine {i}",
                )
            )
            drivers.extend(
                make_driver(
                    driver_id=f"d{i}{j}-{year}",
                    name=f"Driver {i}{j} {year}",
                    year=year,
                    constructor_id=f"c{i}",
                    rating=-float(j),
                    main=j < 2,
                )
                for j in range(drivers_per_car)
            )
    return SweepDataset(cars, drivers)
