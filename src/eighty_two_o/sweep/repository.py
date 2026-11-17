"""Loading and indexing the bundled Clean Sweep dataset."""

import csv
import functools
import io
from collections.abc import Iterable
from importlib import resources

from eighty_two_o.sweep.models import CarSeason, DriverSeason

MAIN_DRIVERS = 2


class SweepDataset:
    """Every constructor-season, its drivers, and the fields of every season, indexed."""

    def __init__(self, cars: Iterable[CarSeason], drivers: Iterable[DriverSeason]) -> None:
        """Index the given records.

        Args:
            cars: Every constructor-season.
            drivers: Every driver card, each constructor's in roster order.

        Raises:
            ValueError: On a duplicate car or card, a card whose car is missing, or a car
                without exactly two main drivers.
        """
        self._cars: dict[str, CarSeason] = {}
        for car in sorted(cars, key=lambda c: (c.year, c.constructor_id)):
            if car.key in self._cars:
                raise ValueError(f"duplicate car {car.key}")
            self._cars[car.key] = car

        self._drivers: dict[str, DriverSeason] = {}
        rosters: dict[str, list[DriverSeason]] = {key: [] for key in self._cars}
        for driver in drivers:
            if driver.card_id in self._drivers:
                raise ValueError(f"duplicate card {driver.card_id}")
            if driver.car_key not in self._cars:
                raise ValueError(f"card {driver.card_id} has no car")
            self._drivers[driver.card_id] = driver
            rosters[driver.car_key].append(driver)
        self._rosters = {key: tuple(cards) for key, cards in rosters.items()}
        self._mains = {
            key: tuple(card for card in cards if card.main) for key, cards in self._rosters.items()
        }
        wrong = [key for key, mains in self._mains.items() if len(mains) != MAIN_DRIVERS]
        if wrong:
            raise ValueError(f"cars without exactly two main drivers: {wrong[:5]}")

        self.cars: tuple[CarSeason, ...] = tuple(self._cars.values())
        """Every car, sorted by year then constructor id."""
        self.rollable: tuple[CarSeason, ...] = tuple(car for car in self.cars if car.rollable)
        """The cars the draft rolls from (race winners), in the same order."""
        self.seasons: tuple[int, ...] = tuple(sorted({car.year for car in self.cars}))
        """Every season with a field, in order."""
        self._grids = {
            year: tuple(sorted((c for c in self.cars if c.year == year), key=lambda c: c.key))
            for year in self.seasons
        }

    @property
    def drivers(self) -> tuple[DriverSeason, ...]:
        """Every driver card."""
        return tuple(self._drivers.values())

    def car(self, key: str) -> CarSeason:
        """Look up a car.

        Args:
            key: A key such as ``"williams:1992"``.

        Returns:
            The car.

        Raises:
            KeyError: If there is no such car.
        """
        return self._cars[key]

    def roster(self, key: str) -> tuple[DriverSeason, ...]:
        """List a car's drivers, most starts first.

        Args:
            key: A car key.

        Returns:
            The roster.

        Raises:
            KeyError: If there is no such car.
        """
        return self._rosters[key]

    def mains(self, key: str) -> tuple[DriverSeason, DriverSeason]:
        """The two drivers who drove a car most often that season.

        Args:
            key: A car key.

        Returns:
            Its two main drivers, in roster order.

        Raises:
            KeyError: If there is no such car.
        """
        first, second = self._mains[key]
        return first, second

    def driver(self, card_id: str) -> DriverSeason:
        """Look up a driver card.

        Args:
            card_id: An id such as ``"max-verstappen:2025:red-bull"``.

        Returns:
            The card.

        Raises:
            KeyError: If there is no such card.
        """
        return self._drivers[card_id]

    def grid(self, year: int) -> tuple[CarSeason, ...]:
        """The field of a season: the cars a race against that season is run against.

        Args:
            year: The season.

        Returns:
            That season's cars, sorted by constructor id.

        Raises:
            KeyError: If there is no such season.
        """
        return self._grids[year]


def _blank_to_none(row: dict[str, str]) -> dict[str, str | None]:
    return {key: (None if value == "" else value) for key, value in row.items()}


def parse_car(row: dict[str, str]) -> CarSeason:
    """Convert one row of ``cars.csv`` into a car (empty cells become ``None``).

    Args:
        row: The CSV row.

    Returns:
        The car.
    """
    return CarSeason.model_validate(_blank_to_none(row))


def parse_driver(row: dict[str, str]) -> DriverSeason:
    """Convert one row of ``drivers.csv`` into a card (empty cells become ``None``).

    Args:
        row: The CSV row.

    Returns:
        The card.
    """
    return DriverSeason.model_validate(_blank_to_none(row))


def _read_csv(name: str) -> list[dict[str, str]]:
    text = resources.files("eighty_two_o.sweep").joinpath(name).read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


@functools.cache
def load_sweep_dataset() -> SweepDataset:
    """Load the Clean Sweep dataset bundled with the package (cached after the first call).

    Returns:
        The indexed dataset.
    """
    cars = [parse_car(row) for row in _read_csv("cars.csv")]
    drivers = [parse_driver(row) for row in _read_csv("drivers.csv")]
    return SweepDataset(cars, drivers)
