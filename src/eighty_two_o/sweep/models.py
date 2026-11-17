"""Typed records for the bundled Clean Sweep dataset.

Strengths are on one log scale: in a race, an entrant's chance of winning is proportional to
``exp(strength)``. A car's ``car`` value is its engine, chassis and pit crew added together, and
0 is the average car of its season; a driver's ``rating`` is added to his car's strength.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Slot(StrEnum):
    """A place in the player's team."""

    ENGINE = "engine"
    CHASSIS = "chassis"
    RELIABILITY = "reliability"
    PIT_CREW = "pit_crew"
    DRIVER = "driver"

    @property
    def label(self) -> str:
        """The name shown to the player, e.g. ``"Pit crew"``."""
        return self.value.replace("_", " ").capitalize()


PART_SLOTS: tuple[Slot, ...] = (Slot.ENGINE, Slot.CHASSIS, Slot.RELIABILITY, Slot.PIT_CREW)
"""The four parts of a car, in the order they are shown."""


class CarSeason(BaseModel):
    """One real constructor-season: where every part and driver of the draft comes from.

    ``engine``, ``chassis`` and ``pit`` add up to ``car``. ``reliability`` is the car's
    mechanical retirement rate relative to its season (1.0 is average, lower is better).
    """

    model_config = ConfigDict(frozen=True)

    constructor_id: str
    year: int
    name: str
    chassis_name: str
    engine_id: str
    engine_name: str
    engine_badge: str
    car: float
    engine: float
    chassis: float
    pit: float
    pit_rated: bool
    pit_rank: int | None
    reliability: float
    races: int
    starts: int
    wins: int
    poles: int
    podiums: int
    mechanical_retirements: int
    engine_wins: int
    engine_teams: int
    championship_position: int | None
    rollable: bool

    @property
    def key(self) -> str:
        """Unique key, e.g. ``"williams:1992"``."""
        return f"{self.constructor_id}:{self.year}"

    @property
    def label(self) -> str:
        """Short display name, e.g. ``"1992 Williams"``."""
        return f"{self.year} {self.name}"

    @property
    def full_label(self) -> str:
        """Display name with the car and engine, e.g. ``"1992 Williams FW14B, Renault engine"``."""
        return f"{self.year} {self.name} {self.chassis_name}, {self.engine_name} engine"


class DriverSeason(BaseModel):
    """One driver's season with one constructor: a card that can be drafted.

    ``rating`` is how strong he was that season, used when he races in that season's field.
    ``career`` is his best level (his best seasons, raised to his tier in a published poll of
    the quickest drivers); every one of his cards carries it, and it is what a drafted driver
    races with. ``incident`` is his crash-out rate over his career relative to his eras (1.0 is
    average, lower is better). Counting stats are for this constructor and year.
    """

    model_config = ConfigDict(frozen=True)

    driver_id: str
    name: str
    year: int
    constructor_id: str
    rating: float
    career: float
    incident: float
    starts: int
    wins: int
    poles: int
    podiums: int
    championship_position: int | None
    main: bool

    @property
    def card_id(self) -> str:
        """Unique id, e.g. ``"max-verstappen:2025:red-bull"``."""
        return f"{self.driver_id}:{self.year}:{self.constructor_id}"

    @property
    def car_key(self) -> str:
        """Key of the constructor-season this card belongs to."""
        return f"{self.constructor_id}:{self.year}"

    @property
    def label(self) -> str:
        """Display name with the season, e.g. ``"Max Verstappen (2025)"``."""
        return f"{self.name} ({self.year})"
