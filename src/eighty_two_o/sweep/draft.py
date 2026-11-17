"""The Clean Sweep draft: roll a race-winning constructor-season, take one part or driver.

The state is immutable; every action returns a new one. Each roll uses its own generator
built from the seed, the number of picks made and the rerolls used, so the same seed and the
same choices always give the same rolls.
"""

import random

from pydantic import BaseModel, ConfigDict

from eighty_two_o.config import DEFAULT_SWEEP_DRAFT, SweepDraftConfig
from eighty_two_o.sweep.models import PART_SLOTS, CarSeason, DriverSeason, Slot
from eighty_two_o.sweep.repository import SweepDataset

TEAM_DRIVERS = 3
"""Drivers in a team: two race seats and a reserve."""
ROUNDS = len(PART_SLOTS) + TEAM_DRIVERS
DRIVER_PREFIX = "driver:"


class SweepDraftError(ValueError):
    """A draft action that is not allowed; the message is safe to show the player."""


class SweepDraft(BaseModel):
    """Where a Clean Sweep draft stands."""

    model_config = ConfigDict(frozen=True)

    seed: int
    engine: CarSeason | None = None
    chassis: CarSeason | None = None
    reliability: CarSeason | None = None
    pit_crew: CarSeason | None = None
    drivers: tuple[DriverSeason, ...] = ()
    rerolls_used: int = 0
    current_roll: str | None = None
    """Key of the car on the board; ``None`` once the draft is complete."""
    rolled: tuple[str, ...] = ()
    """Every car shown so far, including rerolled ones."""

    def part(self, slot: Slot) -> CarSeason | None:
        """The car a part slot was taken from, if it is filled.

        Args:
            slot: One of ``PART_SLOTS``.

        Returns:
            The car, or ``None`` while the slot is empty.
        """
        held: CarSeason | None = getattr(self, slot.value)
        return held

    @property
    def open_parts(self) -> tuple[Slot, ...]:
        """The part slots still empty, in display order."""
        return tuple(slot for slot in PART_SLOTS if self.part(slot) is None)

    @property
    def seats_full(self) -> bool:
        """Whether all three drivers have been drafted."""
        return len(self.drivers) >= TEAM_DRIVERS

    @property
    def picks_made(self) -> int:
        """Parts and drivers taken so far."""
        return len(PART_SLOTS) - len(self.open_parts) + len(self.drivers)

    @property
    def complete(self) -> bool:
        """Whether every slot is filled."""
        return self.picks_made == ROUNDS


class PartOption(BaseModel):
    """A part of the car on the board."""

    model_config = ConfigDict(frozen=True)

    slot: Slot
    available: bool
    held: CarSeason | None
    """What the player already has in this slot, if anything."""


class DriverOption(BaseModel):
    """A driver of the car on the board."""

    model_config = ConfigDict(frozen=True)

    card: DriverSeason
    available: bool


class Board(BaseModel):
    """Everything the player can take from the current roll."""

    model_config = ConfigDict(frozen=True)

    car: CarSeason
    parts: tuple[PartOption, ...]
    drivers: tuple[DriverOption, ...]


def _drafted_people(state: SweepDraft) -> set[str]:
    return {driver.driver_id for driver in state.drivers}


def _offers_legal_item(state: SweepDraft, car: CarSeason, dataset: SweepDataset) -> bool:
    if state.open_parts:
        return True  # with no open parts the seats cannot be full, or the draft would be over
    taken = _drafted_people(state)
    return any(driver.driver_id not in taken for driver in dataset.roster(car.key))


def _roll(state: SweepDraft, dataset: SweepDataset) -> SweepDraft:
    rng = random.Random(f"{state.seed}:sweep-roll:{state.picks_made}:{state.rerolls_used}")
    candidates = [
        car
        for car in dataset.rollable
        if car.key not in state.rolled and _offers_legal_item(state, car, dataset)
    ]
    if not candidates:
        raise SweepDraftError("There are no team-seasons left to roll.")
    car = rng.choice(candidates)
    return state.model_copy(update={"current_roll": car.key, "rolled": (*state.rolled, car.key)})


def start_draft(
    dataset: SweepDataset, seed: int, config: SweepDraftConfig = DEFAULT_SWEEP_DRAFT
) -> SweepDraft:
    """Start a draft with its first roll on the board.

    Args:
        dataset: The dataset to draft from.
        seed: The game's seed.
        config: Draft rules.

    Returns:
        The new draft.
    """
    del config  # every rule that matters before the first pick is fixed
    return _roll(SweepDraft(seed=seed), dataset)


def rerolls_left(state: SweepDraft, config: SweepDraftConfig = DEFAULT_SWEEP_DRAFT) -> int:
    """How many rerolls the player still has.

    Args:
        state: The draft.
        config: Draft rules.

    Returns:
        Remaining rerolls.
    """
    return config.rerolls - state.rerolls_used


def reroll(
    state: SweepDraft, dataset: SweepDataset, config: SweepDraftConfig = DEFAULT_SWEEP_DRAFT
) -> SweepDraft:
    """Replace the car on the board with another roll.

    Args:
        state: The draft.
        dataset: The dataset to draft from.
        config: Draft rules.

    Returns:
        The draft with a new roll.

    Raises:
        SweepDraftError: If the draft is complete or no rerolls remain.
    """
    if state.complete:
        raise SweepDraftError("The draft is already over.")
    if rerolls_left(state, config) <= 0:
        raise SweepDraftError("You have no rerolls left.")
    return _roll(state.model_copy(update={"rerolls_used": state.rerolls_used + 1}), dataset)


def pick(
    state: SweepDraft,
    dataset: SweepDataset,
    item: str,
    config: SweepDraftConfig = DEFAULT_SWEEP_DRAFT,
) -> SweepDraft:
    """Take one item from the car on the board.

    Args:
        state: The draft.
        dataset: The dataset to draft from.
        item: A part slot (``"engine"``, ``"chassis"``, ``"reliability"``, ``"pit_crew"``) or
            ``"driver:<card id>"``.
        config: Draft rules.

    Returns:
        The draft with the item taken and, unless that was the last pick, a new roll.

    Raises:
        SweepDraftError: If the draft is complete, the item is not recognised, the slot is
            already filled, the seats are full, the driver is not on the rolled car, or that
            person is already in the team.
    """
    del config  # picks follow the same rules whatever the reroll count
    if state.complete or state.current_roll is None:
        raise SweepDraftError("The draft is already over.")
    car = dataset.car(state.current_roll)

    if item.startswith(DRIVER_PREFIX):
        card_id = item.removeprefix(DRIVER_PREFIX)
        if state.seats_full:
            raise SweepDraftError("All three driver seats are taken.")
        driver = next((d for d in dataset.roster(car.key) if d.card_id == card_id), None)
        if driver is None:
            raise SweepDraftError("That driver did not drive for this team.")
        if driver.driver_id in _drafted_people(state):
            raise SweepDraftError(f"{driver.name} is already in your team.")
        state = state.model_copy(update={"drivers": (*state.drivers, driver)})
    else:
        slot = next((s for s in PART_SLOTS if s.value == item), None)
        if slot is None:
            raise SweepDraftError("That is not something you can take.")
        if state.part(slot) is not None:
            raise SweepDraftError(f"Your {slot.label.lower()} slot is already filled.")
        state = state.model_copy(update={slot.value: car})

    if state.complete:
        return state.model_copy(update={"current_roll": None})
    return _roll(state, dataset)


def board(state: SweepDraft, dataset: SweepDataset) -> Board:
    """Describe the car on the board and what can be taken from it.

    Args:
        state: A draft that is not complete.
        dataset: The dataset to draft from.

    Returns:
        The board.

    Raises:
        SweepDraftError: If the draft is complete.
    """
    if state.current_roll is None:
        raise SweepDraftError("The draft is already over.")
    car = dataset.car(state.current_roll)
    taken = _drafted_people(state)
    parts = tuple(
        PartOption(slot=slot, available=state.part(slot) is None, held=state.part(slot))
        for slot in PART_SLOTS
    )
    drivers = tuple(
        DriverOption(card=d, available=not state.seats_full and d.driver_id not in taken)
        for d in dataset.roster(car.key)
    )
    return Board(car=car, parts=parts, drivers=drivers)
