"""A whole game, from the first roll to the final record, and where games are kept.

A ``Game`` is immutable plain data that round-trips through JSON; every transition returns a
new one. The game moves through three phases: drafting, choosing the lineup, and done (the
season has been simulated).
"""

import secrets
import threading
from collections import OrderedDict
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from eighty_two_o.config import (
    DEFAULT_DRAFT,
    DEFAULT_RATING,
    DEFAULT_SIM,
    DraftConfig,
    RatingConfig,
    SimConfig,
)
from eighty_two_o.data.models import PlayerSeason
from eighty_two_o.data.repository import Dataset
from eighty_two_o.draft import DraftState, pick, reroll, start_draft
from eighty_two_o.rating import STARTERS, TeamRating, rate_team
from eighty_two_o.season import SeasonResult, simulate_season


class Mode(StrEnum):
    """How much the player sees during the draft."""

    ROOKIE = "rookie"
    """Stat lines are shown while drafting."""
    LEGEND = "legend"
    """Only names and positions are shown until the lineup is locked."""


class Phase(StrEnum):
    """Where a game stands."""

    DRAFT = "draft"
    LINEUP = "lineup"
    DONE = "done"


class GameError(ValueError):
    """An action that is not allowed right now; the message is safe to show the player."""


class Game(BaseModel):
    """One play-through."""

    model_config = ConfigDict(frozen=True)

    id: str
    seed: int
    mode: Mode
    draft: DraftState
    starters: tuple[PlayerSeason, ...] = ()
    bench: tuple[PlayerSeason, ...] = ()
    rating: TeamRating | None = None
    season: SeasonResult | None = None

    @property
    def phase(self) -> Phase:
        """The current phase, derived from what has happened so far."""
        if not self.draft.complete:
            return Phase.DRAFT
        if self.season is None:
            return Phase.LINEUP
        return Phase.DONE

    @property
    def stats_visible(self) -> bool:
        """Whether numbers may be shown: always in Rookie mode, at the end in Legend mode."""
        return self.mode is Mode.ROOKIE or self.phase is Phase.DONE


def new_game(
    dataset: Dataset,
    mode: Mode,
    seed: int | None = None,
    draft_config: DraftConfig = DEFAULT_DRAFT,
) -> Game:
    """Start a game with its first roll on the board.

    Args:
        dataset: The dataset to draft from.
        mode: Rookie or Legend.
        seed: The game's seed; a random one when omitted.
        draft_config: Draft rules.

    Returns:
        The new game, in the draft phase.
    """
    seed = secrets.randbits(32) if seed is None else seed
    return Game(
        id=secrets.token_urlsafe(8),
        seed=seed,
        mode=mode,
        draft=start_draft(dataset, seed, draft_config),
    )


def apply_pick(
    game: Game, dataset: Dataset, card_id: str, draft_config: DraftConfig = DEFAULT_DRAFT
) -> Game:
    """Draft a player.

    Args:
        game: The game.
        dataset: The dataset the game drafts from.
        card_id: The card to draft.
        draft_config: Draft rules.

    Returns:
        The game with the pick made.

    Raises:
        GameError: If the draft is over.
        DraftError: If the pick is not legal.
    """
    _require_phase(game, Phase.DRAFT)
    return game.model_copy(update={"draft": pick(game.draft, dataset, card_id, draft_config)})


def apply_reroll(game: Game, dataset: Dataset, draft_config: DraftConfig = DEFAULT_DRAFT) -> Game:
    """Spend a reroll.

    Args:
        game: The game.
        dataset: The dataset the game drafts from.
        draft_config: Draft rules.

    Returns:
        The game with a new team-season on the board.

    Raises:
        GameError: If the draft is over.
        DraftError: If no rerolls remain.
    """
    _require_phase(game, Phase.DRAFT)
    return game.model_copy(update={"draft": reroll(game.draft, dataset, draft_config)})


def lock_lineup(
    game: Game,
    dataset: Dataset,
    starter_card_ids: Sequence[str],
    rating_config: RatingConfig = DEFAULT_RATING,
    sim_config: SimConfig = DEFAULT_SIM,
) -> Game:
    """Choose the five starters, then rate the team and simulate its season.

    Args:
        game: The game, in the lineup phase.
        dataset: Where opponents come from.
        starter_card_ids: Exactly five distinct cards from the drafted players.
        rating_config: Rating constants.
        sim_config: Simulation constants.

    Returns:
        The finished game. Starters and bench keep the order they were drafted in.

    Raises:
        GameError: If the game is not in the lineup phase or the starters are not five
            distinct drafted players.
    """
    _require_phase(game, Phase.LINEUP)
    chosen = set(starter_card_ids)
    if len(chosen) != len(starter_card_ids):
        raise GameError("Each starter can only be chosen once.")
    if len(chosen) != STARTERS:
        raise GameError(f"Choose exactly {STARTERS} starters.")
    drafted = {card.card_id for card in game.draft.picks}
    if not chosen <= drafted:
        raise GameError("Starters must come from your drafted players.")

    starters = tuple(card for card in game.draft.picks if card.card_id in chosen)
    bench = tuple(card for card in game.draft.picks if card.card_id not in chosen)
    rating = rate_team(starters, bench, rating_config)
    season = simulate_season(rating.net, dataset, game.seed, sim_config)
    return game.model_copy(
        update={"starters": starters, "bench": bench, "rating": rating, "season": season}
    )


def _require_phase(game: Game, phase: Phase) -> None:
    if game.phase is not phase:
        messages = {
            Phase.DRAFT: "The draft is already over.",
            Phase.LINEUP: "You can only set the lineup after the draft, before the season.",
        }
        raise GameError(messages[phase])


class GameStore(Protocol):
    """Somewhere to keep games between requests."""

    def get(self, game_id: str) -> Game | None:
        """Return the game with this id, or ``None`` if there is none."""
        ...

    def save(self, game: Game) -> None:
        """Store a game, replacing any earlier version with the same id."""
        ...


class InMemoryGameStore:
    """Keeps the most recently saved games in memory; the oldest are dropped beyond a limit."""

    def __init__(self, max_games: int = 1000) -> None:
        """Create an empty store.

        Args:
            max_games: How many games to keep.
        """
        self._max_games = max_games
        self._games: OrderedDict[str, Game] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, game_id: str) -> Game | None:
        """Return the game with this id, or ``None`` if there is none (or it was dropped)."""
        with self._lock:
            return self._games.get(game_id)

    def save(self, game: Game) -> None:
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
