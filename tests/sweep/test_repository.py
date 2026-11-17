import statistics
from collections import Counter

import pytest

from eighty_two_o.sweep.repository import SweepDataset, parse_car, parse_driver
from tests.factories import make_car, make_driver, make_sweep_dataset

TOLERANCE = 0.02


class TestIndexing:
    def test_lookups(self) -> None:
        dataset = make_sweep_dataset(drivers_per_car=3)

        assert [car.key for car in dataset.grid(2000)] == [
            "c0:2000",
            "c1:2000",
            "c2:2000",
            "c3:2000",
        ]
        assert dataset.seasons == (2000, 2001)
        assert len(dataset.rollable) == 8
        assert [d.driver_id for d in dataset.roster("c1:2000")] == [
            "d10-2000",
            "d11-2000",
            "d12-2000",
        ]
        assert [d.driver_id for d in dataset.mains("c1:2000")] == ["d10-2000", "d11-2000"]
        assert dataset.driver("d10-2000:2000:c1").rating == 0.0
        assert dataset.car("c3:2001").car == 1.0
        assert len(dataset.drivers) == 24

    def test_cars_are_sorted_by_year_then_constructor(self) -> None:
        cars = [make_car(constructor_id="b", year=2001), make_car(constructor_id="a", year=2001)]
        cars.append(make_car(constructor_id="z", year=2000))
        drivers = [
            make_driver(
                driver_id=f"{c.constructor_id}{j}", year=c.year, constructor_id=c.constructor_id
            )
            for c in cars
            for j in range(2)
        ]

        dataset = SweepDataset(cars, drivers)

        assert [car.key for car in dataset.cars] == ["z:2000", "a:2001", "b:2001"]

    def test_unknown_ids(self) -> None:
        dataset = make_sweep_dataset()

        for lookup, key in (
            (dataset.car, "nope:2000"),
            (dataset.roster, "nope:2000"),
            (dataset.mains, "nope:2000"),
            (dataset.driver, "nope"),
        ):
            with pytest.raises(KeyError):
                lookup(key)
        with pytest.raises(KeyError):
            dataset.grid(1999)

    def test_rejects_bad_data(self) -> None:
        car = make_car()
        first = make_driver(driver_id="a")
        second = make_driver(driver_id="b")

        with pytest.raises(ValueError, match="duplicate car"):
            SweepDataset([car, car], [first, second])
        with pytest.raises(ValueError, match="duplicate card"):
            SweepDataset([car], [first, first, second])
        with pytest.raises(ValueError, match="has no car"):
            SweepDataset([car], [first, second, make_driver(driver_id="c", year=1999)])
        with pytest.raises(ValueError, match="two main"):
            SweepDataset([car], [first, second.model_copy(update={"main": False})])

    def test_parse_blank_cells_as_none(self) -> None:
        car = make_car()
        row = {key: str(value).lower() for key, value in car.model_dump().items()}
        row |= {"pit_rank": "", "championship_position": ""}

        parsed = parse_car(row)

        assert parsed.pit_rank is None
        assert parsed.championship_position is None
        assert parsed.rollable is True
        driver = make_driver()
        driver_row = {key: str(value).lower() for key, value in driver.model_dump().items()}
        assert parse_driver(driver_row | {"name": driver.name}) == driver


# Each value is (car, engine, chassis, pit, reliability).
PINNED_CARS = {
    "williams:1992": (7.519, 2.305, 5.214, 0.000, 0.608),
    "mercedes:2014": (5.878, 3.187, 2.619, 0.072, 0.887),
    "red-bull:2011": (6.958, 1.454, 5.163, 0.342, 0.437),
    "mclaren:1988": (4.836, 1.959, 2.877, 0.000, 0.346),
    "red-bull:2023": (2.972, 0.588, 1.971, 0.413, 0.543),
    "ferrari:2019": (3.064, 1.583, 1.287, 0.194, 1.154),
    "mclaren:2001": (3.631, 1.815, 1.215, 0.600, 1.095),
    "benetton:1995": (3.288, 2.972, -0.157, 0.473, 0.308),
    "mclaren:2015": (-2.296, -2.148, -0.162, 0.014, 1.788),
    "minardi:2001": (-4.641, -2.320, -1.982, -0.338, 1.601),
}
PINNED_DRIVERS = {
    "max-verstappen:2025:red-bull": (3.071, 0.970),
    "michael-schumacher:1994:benetton": (2.735, 0.784),
    "ayrton-senna:1989:mclaren": (1.916, 0.838),
    "alain-prost:1986:mclaren": (1.582, 0.613),
    "lewis-hamilton:2018:mercedes": (1.201, 0.730),
    "fernando-alonso:2001:minardi": (0.637, 0.638),
    "pastor-maldonado:2012:williams": (0.004, 1.632),
    "sergio-perez:2023:red-bull": (-0.672, 0.961),
}


class TestBundledData:
    def test_counts(self, sweep_dataset: SweepDataset) -> None:
        cars = sweep_dataset.cars

        assert len(cars) == 516
        assert len(sweep_dataset.rollable) == 164
        assert len(sweep_dataset.drivers) == 1121
        assert len(sweep_dataset.seasons) == 46
        assert sweep_dataset.seasons[0] == 1980
        assert sweep_dataset.seasons[-1] == 2025
        per_season = Counter(car.year for car in cars)
        assert min(per_season.values()) == 10
        assert max(per_season.values()) == 14
        assert len({(car.engine_id, car.year) for car in cars}) == 275
        assert sum(car.pit_rated for car in cars) == 342

    @pytest.mark.parametrize(("key", "expected"), PINNED_CARS.items())
    def test_pinned_cars(
        self, sweep_dataset: SweepDataset, key: str, expected: tuple[float, ...]
    ) -> None:
        car = sweep_dataset.car(key)
        actual = (car.car, car.engine, car.chassis, car.pit, car.reliability)

        assert actual == pytest.approx(expected, abs=TOLERANCE)
        assert car.rollable is (key not in {"mclaren:2015", "minardi:2001"})

    @pytest.mark.parametrize(("card_id", "expected"), PINNED_DRIVERS.items())
    def test_pinned_drivers(
        self, sweep_dataset: SweepDataset, card_id: str, expected: tuple[float, float]
    ) -> None:
        driver = sweep_dataset.driver(card_id)

        assert (driver.rating, driver.incident) == pytest.approx(expected, abs=TOLERANCE)

    def test_consistency(self, sweep_dataset: SweepDataset) -> None:
        cars = sweep_dataset.cars
        for car in cars:
            assert car.engine + car.chassis + car.pit == pytest.approx(car.car, abs=1e-6)
            assert len(sweep_dataset.mains(car.key)) == 2
            assert car.pit_rated == (car.pit_rank is not None)
        for year in sweep_dataset.seasons:
            mean = statistics.fmean(car.car for car in sweep_dataset.grid(year))
            assert mean == pytest.approx(0, abs=0.01)
        engines: dict[tuple[str, int], set[float]] = {}
        for car in cars:
            engines.setdefault((car.engine_id, car.year), set()).add(car.engine)
        assert all(len(values) == 1 for values in engines.values())
        assert len({d.card_id for d in sweep_dataset.drivers}) == 1121

    def test_ranges(self, sweep_dataset: SweepDataset) -> None:
        cars = sweep_dataset.cars
        drivers = sweep_dataset.drivers
        for values, low, high in (
            ([c.car for c in cars], -6.083, 7.519),
            ([c.engine for c in cars], -2.534, 3.187),
            ([c.chassis for c in cars], -5.855, 5.214),
            ([c.pit for c in cars], -0.6, 0.6),
            ([c.reliability for c in cars], 0.308, 2.065),
            ([d.rating for d in drivers], -2.995, 3.071),
            ([d.incident for d in drivers], 0.401, 2.024),
        ):
            assert min(values) == pytest.approx(low, abs=TOLERANCE)
            assert max(values) == pytest.approx(high, abs=TOLERANCE)

    def test_orders(self, sweep_dataset: SweepDataset) -> None:
        engines = {(c.engine_name, c.year): c.engine for c in sweep_dataset.cars}
        best_engines = sorted(engines, key=lambda key: -engines[key])[:5]
        assert best_engines == [
            ("Mercedes", 2014),
            ("Renault", 1995),
            ("Mercedes", 2015),
            ("Renault", 1991),
            ("Mercedes", 2016),
        ]
        chassis = sorted(sweep_dataset.cars, key=lambda c: -c.chassis)[:4]
        assert [c.key for c in chassis] == [
            "williams:1992",
            "red-bull:2011",
            "ferrari:2007",
            "red-bull:2010",
        ]
        best: dict[str, float] = {}
        for d in sweep_dataset.drivers:
            best[d.name] = max(best.get(d.name, d.rating), d.rating)
        assert sorted(best, key=lambda name: -best[name])[:5] == [
            "Max Verstappen",
            "Michael Schumacher",
            "Ayrton Senna",
            "Alain Prost",
            "Fernando Alonso",
        ]

    def test_facts(self, sweep_dataset: SweepDataset) -> None:
        williams = sweep_dataset.car("williams:1992")
        assert (williams.wins, williams.poles, williams.podiums) == (10, 15, 21)
        assert (williams.races, williams.starts, williams.mechanical_retirements) == (16, 32, 5)
        assert williams.championship_position == 1
        assert williams.chassis_name == "FW14B"
        assert williams.engine_name == "Renault"
        red_bull = sweep_dataset.car("red-bull:2023")
        assert (red_bull.wins, red_bull.races, red_bull.mechanical_retirements) == (21, 22, 0)
        assert (red_bull.engine_id, red_bull.engine_badge) == ("honda", "Honda RBPT")
        mercedes = sweep_dataset.car("mercedes:2014")
        assert (mercedes.engine_wins, mercedes.engine_teams) == (16, 4)
        assert sum(c.championship_position is None for c in sweep_dataset.cars) == 32
