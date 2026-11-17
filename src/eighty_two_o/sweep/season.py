"""The Clean Sweep season: 20 races, each against the real field of a different season.

In every race each car may retire (mechanical failure or an incident); the running cars are
then ordered by strength plus Gumbel noise, so an entrant wins with probability proportional to
``exp(strength)`` among those still running. The player wins a race when one of their two cars
finishes first.
"""

import math
import random
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from eighty_two_o.config import DEFAULT_SWEEP_SIM, SweepSimConfig
from eighty_two_o.sweep.models import DriverSeason
from eighty_two_o.sweep.repository import SweepDataset
from eighty_two_o.sweep.team import Team, car_strength, retirement_chances

type Retirement = Literal["mechanical", "incident"]


class CarResult(BaseModel):
    """How one of the player's cars did in a race."""

    model_config = ConfigDict(frozen=True)

    driver: str
    reserve: bool
    """Whether the reserve drove this car."""
    position: int | None
    """Finishing position; ``None`` if the car retired."""
    retirement: Retirement | None


class RaceResult(BaseModel):
    """One race of the season."""

    model_config = ConfigDict(frozen=True)

    number: int
    year: int
    """The season whose field this race was run against."""
    won: bool
    winner: str | None
    """The winning driver's name; ``None`` if nobody finished."""
    winner_car: str | None
    """The winning rival's car, e.g. ``"1992 Williams"``; ``None`` when the player won."""
    cars: tuple[CarResult, CarResult]
    finishers: int


class SweepSeason(BaseModel):
    """A whole Clean Sweep season."""

    model_config = ConfigDict(frozen=True)

    races: tuple[RaceResult, ...]

    @property
    def wins(self) -> int:
        """Races won."""
        return sum(race.won for race in self.races)

    @property
    def losses(self) -> int:
        """Races lost."""
        return len(self.races) - self.wins

    @property
    def record(self) -> str:
        """The result as displayed, e.g. ``"17 of 20"``."""
        return f"{self.wins} of {len(self.races)}"

    @property
    def perfect(self) -> bool:
        """Whether every race was won: a clean sweep."""
        return self.wins == len(self.races)

    @property
    def first_loss(self) -> RaceResult | None:
        """The first race not won, if any."""
        return next((race for race in self.races if not race.won), None)

    @property
    def longest_win_streak(self) -> int:
        """The most races won in a row."""
        best = current = 0
        for race in self.races:
            current = current + 1 if race.won else 0
            best = max(best, current)
        return best

    @property
    def one_twos(self) -> int:
        """Races where the player's cars finished first and second."""
        return sum({car.position for car in race.cars} == {1, 2} for race in self.races)

    @property
    def retirements(self) -> int:
        """How many times one of the player's cars retired."""
        return sum(car.retirement is not None for race in self.races for car in race.cars)

    @property
    def beaten_by(self) -> tuple[RaceResult, ...]:
        """The races lost, in order."""
        return tuple(race for race in self.races if not race.won)


@dataclass(frozen=True)
class _Entrant:
    strength: float
    mechanical: float
    incident: float
    driver: str
    car: str | None
    """The rival car's label; ``None`` for the player's cars."""


def _field(dataset: SweepDataset, year: int, config: SweepSimConfig) -> list[_Entrant]:
    entrants = []
    for car in dataset.grid(year):
        for driver in dataset.mains(car.key):
            mechanical, incident = retirement_chances(car.reliability, driver.incident, config)
            entrants.append(
                _Entrant(car.car + driver.rating, mechanical, incident, driver.name, car.label)
            )
    return entrants


def simulate_season(
    team: Team, dataset: SweepDataset, seed: int, config: SweepSimConfig = DEFAULT_SWEEP_SIM
) -> SweepSeason:
    """Run the player's team through a season of races against real fields.

    Args:
        team: The player's team.
        dataset: Where the fields come from.
        seed: The game's seed; the same seed and team always give the same season.
        config: Simulation constants.

    Returns:
        The season.
    """
    rng = random.Random(f"{seed}:sweep-season")
    years = rng.sample(dataset.seasons, config.races)
    fields = {year: _field(dataset, year, config) for year in years}
    strength = car_strength(team)
    reliability = team.reliability.reliability

    races = []
    for number, year in enumerate(years, start=1):
        seats: list[DriverSeason] = list(team.mains)
        reserve = [False, False]
        absence = rng.random()
        if absence < config.absence_rate:
            seats[0], reserve[0] = team.reserve, True
        elif absence < 2 * config.absence_rate:
            seats[1], reserve[1] = team.reserve, True
        own = [
            _Entrant(
                d.rating + strength,
                *retirement_chances(reliability, d.incident, config),
                d.name,
                None,
            )
            for d in seats
        ]
        entrants = own + fields[year]

        retired: list[Retirement | None] = []
        for entrant in entrants:
            roll = rng.random()
            if roll < entrant.mechanical:
                retired.append("mechanical")
            elif roll < entrant.mechanical + entrant.incident:
                retired.append("incident")
            else:
                retired.append(None)
        scores = {
            i: entrant.strength - math.log(-math.log(max(rng.random(), 1e-12)))
            for i, entrant in enumerate(entrants)
            if retired[i] is None
        }
        order = sorted(scores, key=lambda i: (-scores[i], i))
        positions = {i: place for place, i in enumerate(order, start=1)}
        winner = entrants[order[0]] if order else None
        won = bool(order) and order[0] < len(own)

        cars = tuple(
            CarResult(
                driver=driver.name,
                reserve=reserve[i],
                position=positions.get(i),
                retirement=retired[i],
            )
            for i, driver in enumerate(seats)
        )
        races.append(
            RaceResult(
                number=number,
                year=year,
                won=won,
                winner=None if winner is None else winner.driver,
                winner_car=None if winner is None or won else winner.car,
                cars=(cars[0], cars[1]),
                finishers=len(order),
            )
        )
    return SweepSeason(races=tuple(races))
