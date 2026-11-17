"""A whole Clean Sweep game, from the first roll to the last race.

Like the basketball ``Game``, a ``SweepGame`` is immutable plain data that round-trips through
JSON, and it moves through the same three phases: drafting, choosing the reserve, and done.
"""

import secrets

from pydantic import BaseModel, ConfigDict

from eighty_two_o.config import (
    DEFAULT_SWEEP_DRAFT,
    DEFAULT_SWEEP_SIM,
    SweepDraftConfig,
    SweepSimConfig,
)
from eighty_two_o.game import GameError, Mode, Phase
from eighty_two_o.sweep.draft import SweepDraft, pick, reroll, start_draft
from eighty_two_o.sweep.models import PART_SLOTS
from eighty_two_o.sweep.repository import SweepDataset
from eighty_two_o.sweep.season import SweepSeason, simulate_season
from eighty_two_o.sweep.team import Team


class SweepGame(BaseModel):
    """One Clean Sweep play-through."""

    model_config = ConfigDict(frozen=True)

    id: str
    seed: int
    mode: Mode
    draft: SweepDraft
    team: Team | None = None
    season: SweepSeason | None = None

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
    dataset: SweepDataset,
    mode: Mode,
    seed: int | None = None,
    draft_config: SweepDraftConfig = DEFAULT_SWEEP_DRAFT,
) -> SweepGame:
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
    return SweepGame(
        id=secrets.token_urlsafe(8),
        seed=seed,
        mode=mode,
        draft=start_draft(dataset, seed, draft_config),
    )


def apply_pick(
    game: SweepGame,
    dataset: SweepDataset,
    item: str,
    draft_config: SweepDraftConfig = DEFAULT_SWEEP_DRAFT,
) -> SweepGame:
    """Take a part or a driver.

    Args:
        game: The game.
        dataset: The dataset the game drafts from.
        item: What to take (see ``sweep.draft.pick``).
        draft_config: Draft rules.

    Returns:
        The game with the pick made.

    Raises:
        GameError: If the draft is over.
        SweepDraftError: If the pick is not legal.
    """
    _require_phase(game, Phase.DRAFT)
    return game.model_copy(update={"draft": pick(game.draft, dataset, item, draft_config)})


def apply_reroll(
    game: SweepGame, dataset: SweepDataset, draft_config: SweepDraftConfig = DEFAULT_SWEEP_DRAFT
) -> SweepGame:
    """Spend a reroll.

    Args:
        game: The game.
        dataset: The dataset the game drafts from.
        draft_config: Draft rules.

    Returns:
        The game with a new car on the board.

    Raises:
        GameError: If the draft is over.
        SweepDraftError: If no rerolls remain.
    """
    _require_phase(game, Phase.DRAFT)
    return game.model_copy(update={"draft": reroll(game.draft, dataset, draft_config)})


def lock_lineup(
    game: SweepGame,
    dataset: SweepDataset,
    reserve_card_id: str,
    sim_config: SweepSimConfig = DEFAULT_SWEEP_SIM,
) -> SweepGame:
    """Choose the reserve, then build the team and run its season.

    Args:
        game: The game, in the lineup phase.
        dataset: Where the rival fields come from.
        reserve_card_id: One of the three drafted drivers.
        sim_config: Simulation constants.

    Returns:
        The finished game. The other two drivers race, in the order they were drafted.

    Raises:
        GameError: If the game is not in the lineup phase or the reserve was not drafted.
    """
    _require_phase(game, Phase.LINEUP)
    drafted = game.draft.drivers
    if reserve_card_id not in {d.card_id for d in drafted}:
        raise GameError("Choose one of your three drivers as the reserve.")
    first, second = (d for d in drafted if d.card_id != reserve_card_id)
    reserve = next(d for d in drafted if d.card_id == reserve_card_id)
    parts = {slot.value: game.draft.part(slot) for slot in PART_SLOTS}
    team = Team.model_validate({**parts, "mains": (first, second), "reserve": reserve})
    season = simulate_season(team, dataset, game.seed, sim_config)
    return game.model_copy(update={"team": team, "season": season})


def _require_phase(game: SweepGame, phase: Phase) -> None:
    if game.phase is not phase:
        messages = {
            Phase.DRAFT: "The draft is already over.",
            Phase.LINEUP: "You can only choose the reserve after the draft, before the season.",
        }
        raise GameError(messages[phase])
