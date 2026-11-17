"""Where games are kept between requests, for any kind of game with an ``id``."""

import threading
from collections import OrderedDict
from typing import Protocol


class Identified(Protocol):
    """Anything with a string id."""

    @property
    def id(self) -> str:
        """The unique id."""
        ...


class Store[G: Identified](Protocol):
    """Somewhere to keep games between requests."""

    def get(self, game_id: str) -> G | None:
        """Return the game with this id, or ``None`` if there is none."""
        ...

    def save(self, game: G) -> None:
        """Store a game, replacing any earlier version with the same id."""
        ...


class InMemoryStore[G: Identified]:
    """Keeps the most recently saved games in memory; the oldest are dropped beyond a limit."""

    def __init__(self, max_games: int = 1000) -> None:
        """Create an empty store.

        Args:
            max_games: How many games to keep.
        """
        self._max_games = max_games
        self._games: OrderedDict[str, G] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, game_id: str) -> G | None:
        """Return the game with this id, or ``None`` if there is none (or it was dropped)."""
        with self._lock:
            return self._games.get(game_id)

    def save(self, game: G) -> None:
        """Store a game as the most recent one, dropping the oldest beyond the limit."""
        with self._lock:
            self._games[game.id] = game
            self._games.move_to_end(game.id)
            while len(self._games) > self._max_games:
                self._games.popitem(last=False)

    def __len__(self) -> int:
        """Return the number of games kept."""
        with self._lock:
            return len(self._games)
