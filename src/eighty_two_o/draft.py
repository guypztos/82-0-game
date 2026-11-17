"""The draft: roll a random real team-season, pick one of its players, repeat.

Every function here is pure. A roll's randomness comes only from the seed and how far the
draft has progressed, so the same seed and the same choices always replay the same draft.
"""

import random

from pydantic import BaseModel, ConfigDict

from eighty_two_o.config import DEFAULT_DRAFT, DraftConfig
from eighty_two_o.data.models import PlayerSeason
from eighty_two_o.data.repository import Dataset


class DraftError(ValueError):
    """An illegal draft move; the message is safe to show the player."""


class DraftState(BaseModel):
    """Where a draft stands."""

    model_config = ConfigDict(frozen=True)

    seed: int
    picks: tuple[PlayerSeason, ...] = ()
    rerolls_used: int = 0
    current_roll: str | None
    """Key of the team-season on the board, or ``None`` once the draft is complete."""
    rolled: tuple[str, ...] = ()
    """Every team-season shown so far, including rerolled ones."""

    @property
    def complete(self) -> bool:
        """Whether every pick has been made."""
        return self.current_roll is None


class RosterEntry(BaseModel):
    """One player on the rolled roster."""

    model_config = ConfigDict(frozen=True)

    card: PlayerSeason
    available: bool
    """False when the same person was already drafted (from any season)."""


def start_draft(dataset: Dataset, seed: int, config: DraftConfig = DEFAULT_DRAFT) -> DraftState:
    """Begin a draft and make its first roll.

    Args:
        dataset: Where team-seasons are rolled from.
        seed: The game's seed.
        config: Draft rules.

    Returns:
        A draft with the first team-season on the board.
    """
    del config  # accepted for a uniform signature; the first roll does not depend on it
    first = _roll(dataset, seed, picks=0, rerolls_used=0, rolled=())
    return DraftState(seed=seed, current_roll=first, rolled=(first,))


def reroll(state: DraftState, dataset: Dataset, config: DraftConfig = DEFAULT_DRAFT) -> DraftState:
    """Replace the team-season on the board with a new one, spending a reroll.

    Args:
        state: The current draft.
        dataset: Where team-seasons are rolled from.
        config: Draft rules.

    Returns:
        The draft with a new team-season on the board.

    Raises:
        DraftError: If the draft is complete or no rerolls remain.
    """
    if state.complete:
        raise DraftError("The draft is already over.")
    if rerolls_left(state, config) <= 0:
        raise DraftError("You have no rerolls left.")
    rerolls_used = state.rerolls_used + 1
    new_roll = _roll(dataset, state.seed, len(state.picks), rerolls_used, state.rolled)
    return state.model_copy(
        update={
            "rerolls_used": rerolls_used,
            "current_roll": new_roll,
            "rolled": (*state.rolled, new_roll),
        }
    )


def pick(
    state: DraftState, dataset: Dataset, card_id: str, config: DraftConfig = DEFAULT_DRAFT
) -> DraftState:
    """Draft a player from the team-season on the board.

    Args:
        state: The current draft.
        dataset: Where team-seasons are rolled from.
        card_id: The card to draft; it must be on the current roster.
        config: Draft rules.

    Returns:
        The draft with the pick added and the next team-season on the board, or complete
        after the last pick.

    Raises:
        DraftError: If the draft is complete, the card is not on the current roster, or the
            same person was already drafted.
    """
    if state.current_roll is None:
        raise DraftError("The draft is already over.")
    card = next((c for c in dataset.roster(state.current_roll) if c.card_id == card_id), None)
    if card is None:
        raise DraftError("That player is not on this roster.")
    if card.player_id in _drafted_people(state):
        raise DraftError(f"You already drafted {card.name}.")

    picks = (*state.picks, card)
    if len(picks) >= config.rounds:
        return state.model_copy(update={"picks": picks, "current_roll": None})
    next_roll = _roll(dataset, state.seed, len(picks), state.rerolls_used, state.rolled)
    return state.model_copy(
        update={"picks": picks, "current_roll": next_roll, "rolled": (*state.rolled, next_roll)}
    )


def roster_view(state: DraftState, dataset: Dataset) -> tuple[RosterEntry, ...]:
    """List the roster on the board, marking players who can no longer be drafted.

    Args:
        state: The current draft.
        dataset: The dataset the draft rolls from.

    Returns:
        The current roster in roster order (most minutes first), or an empty tuple once the
        draft is complete.
    """
    if state.current_roll is None:
        return ()
    drafted = _drafted_people(state)
    return tuple(
        RosterEntry(card=card, available=card.player_id not in drafted)
        for card in dataset.roster(state.current_roll)
    )


def rerolls_left(state: DraftState, config: DraftConfig = DEFAULT_DRAFT) -> int:
    """Count the rerolls still available.

    Args:
        state: The current draft.
        config: Draft rules.

    Returns:
        The number of rerolls left, never negative.
    """
    return max(0, config.rerolls - state.rerolls_used)


def _drafted_people(state: DraftState) -> set[str]:
    return {card.player_id for card in state.picks}


def _roll(
    dataset: Dataset, seed: int, picks: int, rerolls_used: int, rolled: tuple[str, ...]
) -> str:
    seen = set(rolled)
    choices = [team.key for team in dataset.team_seasons if team.key not in seen]
    if not choices:
        raise DraftError("There are no team-seasons left to roll.")
    rng = random.Random(f"{seed}:roll:{picks}:{rerolls_used}")
    return rng.choice(choices)
