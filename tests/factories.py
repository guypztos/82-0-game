"""Small hand-built records for unit tests that should not depend on the real dataset."""

from eighty_two_o.data.models import PlayerSeason, Position, TeamSeason
from eighty_two_o.data.repository import Dataset


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
