"""Simulate an 82-game season against real historical team-seasons.

Each game's margin is drawn around the difference between the two teams' net ratings plus
home-court edge. Everything comes from one generator seeded with the game's seed, so the same
seed and the same team rating always produce the same season.
"""

import random

from pydantic import BaseModel, ConfigDict

from eighty_two_o.config import DEFAULT_SIM, SimConfig
from eighty_two_o.data.models import TeamSeason
from eighty_two_o.data.repository import Dataset


class GameResult(BaseModel):
    """One game of the season, from the drafted team's point of view."""

    model_config = ConfigDict(frozen=True)

    number: int
    """1 to 82, in schedule order."""
    opponent: TeamSeason
    home: bool
    won: bool
    team_points: int
    opponent_points: int

    @property
    def margin(self) -> int:
        """Points scored minus points allowed: positive in a win."""
        return self.team_points - self.opponent_points


class SeasonResult(BaseModel):
    """A whole simulated season."""

    model_config = ConfigDict(frozen=True)

    games: tuple[GameResult, ...]

    @property
    def wins(self) -> int:
        """Games won."""
        return sum(game.won for game in self.games)

    @property
    def losses(self) -> int:
        """Games lost."""
        return len(self.games) - self.wins

    @property
    def record(self) -> str:
        """The record, e.g. ``"81-1"``."""
        return f"{self.wins}-{self.losses}"

    @property
    def perfect(self) -> bool:
        """Whether every game was won."""
        return self.losses == 0

    @property
    def first_loss(self) -> GameResult | None:
        """The first game lost, if any."""
        return next((game for game in self.games if not game.won), None)

    @property
    def longest_win_streak(self) -> int:
        """The most consecutive wins."""
        longest = current = 0
        for game in self.games:
            current = current + 1 if game.won else 0
            longest = max(longest, current)
        return longest

    @property
    def biggest_win(self) -> GameResult | None:
        """The win with the largest margin, if any (the earliest on a tie)."""
        wins = [game for game in self.games if game.won]
        return max(wins, key=lambda game: game.margin, default=None)

    @property
    def worst_loss(self) -> GameResult | None:
        """The loss with the largest margin, if any (the earliest on a tie)."""
        losses = [game for game in self.games if not game.won]
        return min(losses, key=lambda game: game.margin, default=None)

    @property
    def losses_to(self) -> tuple[TeamSeason, ...]:
        """The teams that beat you, in schedule order."""
        return tuple(game.opponent for game in self.games if not game.won)


def build_schedule(
    dataset: Dataset, rng: random.Random, config: SimConfig = DEFAULT_SIM
) -> list[tuple[TeamSeason, bool]]:
    """Draw a season's opponents: all different, half at home, in random order.

    Args:
        dataset: Where opponents come from.
        rng: The season's random generator.
        config: Simulation constants.

    Returns:
        ``(opponent, is_home)`` pairs in schedule order.
    """
    opponents = rng.sample(dataset.team_seasons, config.games)
    schedule = [(opponent, i < config.games // 2) for i, opponent in enumerate(opponents)]
    rng.shuffle(schedule)
    return schedule


def simulate_season(
    net: float, dataset: Dataset, seed: int, config: SimConfig = DEFAULT_SIM
) -> SeasonResult:
    """Play a full season.

    Args:
        net: The drafted team's net rating (see ``rating.rate_team``).
        dataset: Where opponents come from.
        seed: The game's seed.
        config: Simulation constants.

    Returns:
        Every game's result, in schedule order.
    """
    rng = random.Random(f"{seed}:season")
    games = []
    for number, (opponent, home) in enumerate(build_schedule(dataset, rng, config), start=1):
        edge = config.home_edge if home else -config.home_edge
        margin = rng.gauss(net - opponent.net_rating + edge, config.sigma)
        won = margin > 0
        shown_margin = max(1, round(abs(margin)))
        total = round(rng.gauss(config.total_points_mean, config.total_points_sd))
        total = min(config.total_points_max, max(config.total_points_min, total))
        loser_points = max(config.loser_points_min, (total - shown_margin) // 2)
        winner_points = loser_points + shown_margin
        games.append(
            GameResult(
                number=number,
                opponent=opponent,
                home=home,
                won=won,
                team_points=winner_points if won else loser_points,
                opponent_points=loser_points if won else winner_points,
            )
        )
    return SeasonResult(games=tuple(games))
