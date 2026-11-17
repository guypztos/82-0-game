"""Typed records for the bundled NBA dataset."""

from enum import IntEnum

from pydantic import BaseModel, ConfigDict


class Position(IntEnum):
    """A player's primary position, ordered from guard to centre.

    The value is the position's place on the PG-SG-SF-PF-C line, so the distance between two
    positions is the absolute difference of their values.
    """

    PG = 0
    SG = 1
    SF = 2
    PF = 3
    C = 4


def format_season(season: int) -> str:
    """Format a season's end year the way basketball fans write it.

    Args:
        season: The year the season ends in, e.g. 2016.

    Returns:
        The two-year label, e.g. ``"2015-16"``.
    """
    return f"{season - 1}-{season % 100:02d}"


class PlayerSeason(BaseModel):
    """One player's season with one team: a card that can be drafted.

    Counting stats are per game. ``true_shooting`` is a fraction (0.669), ``usage``,
    ``assist_pct`` and ``rebound_pct`` are percentages (32.6), and ``obpm`` / ``dbpm`` are
    offensive and defensive Box Plus/Minus in points per 100 possessions.
    """

    model_config = ConfigDict(frozen=True)

    player_id: str
    name: str
    season: int
    team: str
    position: Position
    age: int
    games: int
    minutes_total: int
    points: float
    rebounds: float
    assists: float
    steals: float
    blocks: float
    turnovers: float
    true_shooting: float
    usage: float
    assist_pct: float
    rebound_pct: float
    obpm: float
    dbpm: float

    @property
    def card_id(self) -> str:
        """Unique id of this card: player, season and team."""
        return f"{self.player_id}:{self.season}:{self.team}"

    @property
    def team_key(self) -> str:
        """Key of the team-season this card belongs to."""
        return f"{self.team}:{self.season}"

    @property
    def season_label(self) -> str:
        """The season as displayed, e.g. ``"2015-16"``."""
        return format_season(self.season)

    @property
    def minutes(self) -> float:
        """Minutes per game."""
        return self.minutes_total / self.games


class TeamSeason(BaseModel):
    """One real NBA team's season: something to roll in the draft or to play against."""

    model_config = ConfigDict(frozen=True)

    team: str
    season: int
    name: str
    wins: int
    losses: int
    net_rating: float

    @property
    def key(self) -> str:
        """Unique key of this team-season, e.g. ``"GSW:2016"``."""
        return f"{self.team}:{self.season}"

    @property
    def season_label(self) -> str:
        """The season as displayed, e.g. ``"2015-16"``."""
        return format_season(self.season)

    @property
    def label(self) -> str:
        """Display name, e.g. ``"2015-16 Golden State Warriors"``."""
        return f"{self.season_label} {self.name}"

    @property
    def record(self) -> str:
        """The real win-loss record, e.g. ``"73-9"``."""
        return f"{self.wins}-{self.losses}"
