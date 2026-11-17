"""A finished Clean Sweep team and the numbers derived from it."""

from pydantic import BaseModel, ConfigDict

from eighty_two_o.config import (
    DEFAULT_SWEEP_DISPLAY,
    DEFAULT_SWEEP_SIM,
    SweepDisplayConfig,
    SweepSimConfig,
)
from eighty_two_o.sweep.models import CarSeason, DriverSeason, Slot


class Team(BaseModel):
    """The player's car (four parts from four real cars) and three drivers."""

    model_config = ConfigDict(frozen=True)

    engine: CarSeason
    chassis: CarSeason
    reliability: CarSeason
    pit_crew: CarSeason
    mains: tuple[DriverSeason, DriverSeason]
    """The two race drivers."""
    reserve: DriverSeason

    def part(self, slot: Slot) -> CarSeason:
        """The car a part came from.

        Args:
            slot: One of ``PART_SLOTS``.

        Returns:
            The car.
        """
        car: CarSeason = getattr(self, slot.value)
        return car

    @property
    def drivers(self) -> tuple[DriverSeason, DriverSeason, DriverSeason]:
        """The two race drivers, then the reserve."""
        return (*self.mains, self.reserve)


def car_strength(team: Team) -> float:
    """The strength of the player's car: its engine, chassis and pit crew added up.

    Args:
        team: The team.

    Returns:
        The car's strength on the same scale as a real car's ``car`` value.
    """
    return team.engine.engine + team.chassis.chassis + team.pit_crew.pit


def part_value(slot: Slot, car: CarSeason) -> float:
    """The number a car contributes when it fills a part slot.

    Args:
        slot: One of ``PART_SLOTS``.
        car: The car the part comes from.

    Returns:
        Its engine, chassis or pit strength, or its reliability ratio (lower is better).

    Raises:
        ValueError: For the driver slot.
    """
    values = {
        Slot.ENGINE: car.engine,
        Slot.CHASSIS: car.chassis,
        Slot.RELIABILITY: car.reliability,
        Slot.PIT_CREW: car.pit,
    }
    if slot not in values:
        raise ValueError(f"{slot} is not a part")
    return values[slot]


def retirement_chances(
    reliability: float, incident: float, config: SweepSimConfig = DEFAULT_SWEEP_SIM
) -> tuple[float, float]:
    """A car's chances of retiring from a race.

    Args:
        reliability: The car's reliability ratio.
        incident: The driver's incident ratio.
        config: Simulation constants.

    Returns:
        ``(mechanical, incident)`` chances; if they add up to more than
        ``retirement_cap``, both are scaled down so that they add up to it.
    """
    mechanical = config.mechanical_rate * reliability
    crash = config.incident_rate * incident
    total = mechanical + crash
    if total > config.retirement_cap:
        scale = config.retirement_cap / total
        return mechanical * scale, crash * scale
    return mechanical, crash


def display_rating(
    slot: Slot, value: float, config: SweepDisplayConfig = DEFAULT_SWEEP_DISPLAY
) -> int:
    """Turn a strength into the 1 to 99 rating shown in Rookie mode.

    Args:
        slot: What the value is.
        value: A part value (see :func:`part_value`) or a driver's rating.
        config: Display constants.

    Returns:
        ``base + scale * value`` rounded and clamped to 1..99; reliability uses
        ``1 - value`` so a more reliable car rates higher.
    """
    scales = {
        Slot.ENGINE: (config.engine_scale, value),
        Slot.CHASSIS: (config.chassis_scale, value),
        Slot.RELIABILITY: (config.reliability_scale, 1 - value),
        Slot.PIT_CREW: (config.pit_scale, value),
        Slot.DRIVER: (config.driver_scale, value),
    }
    scale, x = scales[slot]
    return max(1, min(99, round(config.base + scale * x)))
