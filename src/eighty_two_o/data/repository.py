"""Loading and indexing the bundled dataset."""

import csv
import functools
import io
from collections.abc import Iterable
from importlib import resources

from eighty_two_o.data.models import PlayerSeason, Position, TeamSeason


class Dataset:
    """Every rollable team-season, its roster, and every card, indexed for the game."""

    def __init__(self, players: Iterable[PlayerSeason], teams: Iterable[TeamSeason]) -> None:
        """Index the given records.

        Args:
            players: Every player card.
            teams: Every team-season.

        Raises:
            ValueError: On a duplicate team-season or card, or a card whose team-season is
                not among ``teams``.
        """
        self._teams: dict[str, TeamSeason] = {}
        for team in sorted(teams, key=lambda t: (t.season, t.team)):
            if team.key in self._teams:
                raise ValueError(f"duplicate team-season {team.key}")
            self._teams[team.key] = team

        self._cards: dict[str, PlayerSeason] = {}
        rosters: dict[str, list[PlayerSeason]] = {}
        for player in players:
            if player.card_id in self._cards:
                raise ValueError(f"duplicate card {player.card_id}")
            if player.team_key not in self._teams:
                raise ValueError(f"card {player.card_id} has no team-season")
            self._cards[player.card_id] = player
            rosters.setdefault(player.team_key, []).append(player)

        self._rosters = {
            key: tuple(sorted(cards, key=lambda p: (-p.minutes_total, p.player_id)))
            for key, cards in rosters.items()
        }
        self.team_seasons: tuple[TeamSeason, ...] = tuple(self._teams.values())
        """Every team-season, sorted by season then team: the list the draft rolls from."""

    @property
    def players(self) -> tuple[PlayerSeason, ...]:
        """Every card in the dataset."""
        return tuple(self._cards.values())

    def team(self, team_key: str) -> TeamSeason:
        """Look up a team-season by key.

        Args:
            team_key: A key such as ``"GSW:2016"``.

        Returns:
            The team-season.

        Raises:
            KeyError: If there is no such team-season.
        """
        return self._teams[team_key]

    def roster(self, team_key: str) -> tuple[PlayerSeason, ...]:
        """List a team-season's players, most minutes first.

        Args:
            team_key: A key such as ``"GSW:2016"``.

        Returns:
            The roster, sorted by total minutes (descending) then player id.

        Raises:
            KeyError: If there is no such team-season.
        """
        if team_key not in self._teams:
            raise KeyError(team_key)
        return self._rosters.get(team_key, ())

    def card(self, card_id: str) -> PlayerSeason:
        """Look up a card by id.

        Args:
            card_id: An id such as ``"curryst01:2016:GSW"``.

        Returns:
            The card.

        Raises:
            KeyError: If there is no such card.
        """
        return self._cards[card_id]


def parse_player(row: dict[str, str]) -> PlayerSeason:
    """Convert one row of ``players.csv`` into a card.

    Args:
        row: The CSV row, with positions written as names such as ``"PG"``.

    Returns:
        The card.
    """
    return PlayerSeason.model_validate({**row, "position": Position[row["position"]]})


def parse_team(row: dict[str, str]) -> TeamSeason:
    """Convert one row of ``teams.csv`` into a team-season.

    Args:
        row: The CSV row.

    Returns:
        The team-season.
    """
    return TeamSeason.model_validate(row)


def _read_csv(name: str) -> list[dict[str, str]]:
    text = resources.files("eighty_two_o.data").joinpath(name).read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


@functools.cache
def load_dataset() -> Dataset:
    """Load the dataset bundled with the package (cached after the first call).

    Returns:
        The indexed dataset.
    """
    players = [parse_player(row) for row in _read_csv("players.csv")]
    teams = [parse_team(row) for row in _read_csv("teams.csv")]
    return Dataset(players, teams)
