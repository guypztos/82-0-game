"""Build the bundled Clean Sweep dataset from F1DB race results.

Run it once with ``uv run python tools/build_sweep_dataset.py`` and commit the two CSV files it
writes to ``src/eighty_two_o/sweep/``. The source zip is downloaded from a pinned F1DB release
(github.com/f1db/f1db, CC BY 4.0), checked against its SHA-256 and cached in ``.cache/``.

How the ratings are made:

1. Every qualifying session and race since 1975 is a finishing order. Each entry's strength is
   ``car + driver`` (a car is a constructor-season, a driver is a driver-season), and both are
   fitted at once with a weighted Plackett-Luce model (:func:`fit`).
2. Strengths are centred per season and scaled by ``SHARPNESS`` so that ``exp(strength)``
   reproduces who actually won.
3. A car's strength is split into engine (shared by every team using that engine that year),
   pit crew (from pit-stop times, 1994 on) and chassis (the rest). Written reports adjust the
   engine/chassis split through ``tools/sweep_corrections.csv``.
4. Reliability and each driver's incident rate come from the reasons for retirement.

All rules live in :func:`build` and its helpers, which are pure and unit tested with tiny
hand-written tables; :func:`main` only downloads, reads and writes files.
"""

import argparse
import csv
import hashlib
import io
import itertools
import math
import statistics
import urllib.request
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RELEASE = "v2026.20.0"
URL = f"https://github.com/f1db/f1db/releases/download/{RELEASE}/f1db-csv.zip"
ZIP_SIZE = 4_509_622
ZIP_SHA256 = "0760d50ecb9fad9f267e14ceece73891c2095c812a71d024d0cfbda1f02b3863"

FIT_FIRST_YEAR = 1975
FIRST_YEAR = 1980
LAST_YEAR = 2025
QUALIFYING_WEIGHT = 0.5
CAR_RIDGE = 0.05
DRIVER_RIDGE = 0.4
SMOOTHNESS = 5.0
STEP = 0.3
MOMENTUM = 0.9
ITERATIONS = 1000
SHARPNESS = 1.45
MIN_DRIVER_STARTS = 3
PSEUDO_COUNT = 3.0
PIT_WEIGHT = 0.3
PIT_Z_CAP = 2.0
PIT_SLOW_STOP_SECONDS = 15.0
PIT_MIN_RACES = 5
PIT_MIN_TEAMS = 5

NOT_STARTED = frozenset({"DNQ", "DNPQ", "DNS", "DNP", "EX"})
INCIDENT_REASONS = frozenset(
    {
        "Accident",
        "Accident damage",
        "Collision",
        "Collision damage",
        "Fatal accident",
        "Fatal collision",
        "Puncture damage",
        "Spin",
        "Spun off",
    }
)
IGNORED_REASONS = frozenset(
    {
        "Accident on formation lap",
        "Injury",
        "Physical",
        "Retirement",
        "Tyre shortage",
        "Unfit",
        "Unwell",
        "Withdrew",
    }
)
IGNORED_PREFIX = "Car raced by"
ENGINE_ALIASES = {
    "acer": "ferrari",
    "petronas": "ferrari",
    "european": "ford",
    "fondmetal": "ford",
    "megatron": "bmw",
    "mecachrome": "renault",
    "supertec": "renault",
    "playlife": "renault",
    "tag-heuer": "renault",
    "toro-rosso": "renault",
    "bwt-mercedes": "mercedes",
    "rbpt": "honda",
    "honda-rbpt": "honda",
    "sauber": "ilmor",
}

TABLE_FILES = {
    "races": "f1db-races.csv",
    "results": "f1db-races-race-results.csv",
    "qualifying": "f1db-races-qualifying-results.csv",
    "pit_stops": "f1db-races-pit-stops.csv",
    "drivers": "f1db-drivers.csv",
    "constructors": "f1db-constructors.csv",
    "engines": "f1db-engine-manufacturers.csv",
    "chassis": "f1db-chassis.csv",
    "entrant_chassis": "f1db-seasons-entrants-chassis.csv",
    "constructor_standings": "f1db-seasons-constructor-standings.csv",
    "driver_standings": "f1db-seasons-driver-standings.csv",
}

# Expected sizes for the pinned release.
EXPECTED_SOURCE_RACES = 899
EXPECTED_SOURCE_RESULTS = 21_489
EXPECTED_SOURCE_QUALIFYING = 21_079
EXPECTED_CARS = 516
EXPECTED_ROLLABLE = 164
EXPECTED_DRIVERS = 1_121
EXPECTED_SEASONS = 46
EXPECTED_ENGINE_SEASONS = 275
EXPECTED_PIT_RATED = 342
PIN_TOLERANCE = 0.02
PINNED_CARS = {"williams:1992": 7.519, "mercedes:2014": 5.878, "mclaren:1988": 4.836}
PINNED_DRIVERS = {"max-verstappen:2025:red-bull": 3.071, "ayrton-senna:1989:mclaren": 1.916}

CAR_COLUMNS = (
    "constructor_id",
    "year",
    "name",
    "chassis_name",
    "engine_id",
    "engine_name",
    "engine_badge",
    "car",
    "engine",
    "chassis",
    "pit",
    "pit_rated",
    "pit_rank",
    "reliability",
    "races",
    "starts",
    "wins",
    "poles",
    "podiums",
    "mechanical_retirements",
    "engine_wins",
    "engine_teams",
    "championship_position",
    "rollable",
)
DRIVER_COLUMNS = (
    "driver_id",
    "name",
    "year",
    "constructor_id",
    "rating",
    "incident",
    "starts",
    "wins",
    "poles",
    "podiums",
    "championship_position",
    "main",
)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / f"f1db-{RELEASE}"
OUTPUT_DIR = ROOT / "src" / "eighty_two_o" / "sweep"
CORRECTIONS_FILE = Path(__file__).resolve().parent / "sweep_corrections.csv"

type Row = Mapping[str, str]
type Tables = Mapping[str, Sequence[Row]]
type OutputRow = dict[str, str]
type CarKey = tuple[str, int]
type DriverKey = tuple[str, int]
type EngineKey = tuple[str, int]
type Entry = tuple[CarKey, DriverKey]
type Event = tuple[float, list[Entry]]
type Retirement = Literal["incident", "ignored", "mechanical"]


class DataError(ValueError):
    """The source data breaks one of the assumptions the build relies on."""


@dataclass(frozen=True)
class Correction:
    """A report-based adjustment of one engine-season's share of its cars' strength."""

    engine_id: str
    year: int
    delta: float
    source: str
    note: str


def parse_corrections(rows: Iterable[Row]) -> list[Correction]:
    """Read correction rows (``engine_id, year, delta, source, note``).

    Args:
        rows: Rows of the corrections CSV.

    Returns:
        The corrections.

    Raises:
        DataError: If an engine-season is corrected twice.
    """
    corrections = [
        Correction(
            row["engine_id"], int(row["year"]), float(row["delta"]), row["source"], row["note"]
        )
        for row in rows
    ]
    keys = Counter((c.engine_id, c.year) for c in corrections)
    twice = [key for key, count in keys.items() if count > 1]
    if twice:
        raise DataError(f"engine-seasons corrected more than once: {twice}")
    return corrections


def _year(row: Row) -> int:
    return int(row["year"])


def _in_game(row: Row) -> bool:
    return FIRST_YEAR <= _year(row) <= LAST_YEAR


def is_start(row: Row) -> bool:
    """Whether a race-result row is a start (the car took part in the race).

    Args:
        row: A race-result row.

    Returns:
        ``True`` unless the entry did not qualify, start, or was excluded.
    """
    return row["positionText"] not in NOT_STARTED


def classify_retirement(reason: str) -> Retirement:
    """Say whose fault a retirement was.

    Args:
        reason: The ``reasonRetired`` text of a DNF.

    Returns:
        ``"incident"`` for a crash or spin, ``"ignored"`` for retirements that say nothing
        about the car or driver (illness, withdrawal), ``"mechanical"`` for everything else.
    """
    if reason in INCIDENT_REASONS:
        return "incident"
    if reason in IGNORED_REASONS or reason.startswith(IGNORED_PREFIX):
        return "ignored"
    return "mechanical"


def fit_events(results: Iterable[Row], qualifying: Iterable[Row]) -> list[Event]:
    """Turn qualifying and race results into weighted finishing orders.

    Args:
        results: Race-result rows.
        qualifying: Qualifying-result rows.

    Returns:
        One event per qualifying session (weight ``QUALIFYING_WEIGHT``), then one per race
        (weight 1), each listing ``(car, driver)`` best first. Events with fewer than two
        entries are left out.
    """
    sessions: dict[tuple[int, int], list[tuple[int, str, str]]] = defaultdict(list)
    for row in qualifying:
        if FIT_FIRST_YEAR <= _year(row) <= LAST_YEAR and row["positionNumber"]:
            sessions[(_year(row), int(row["round"]))].append(
                (int(row["positionNumber"]), row["driverId"], row["constructorId"])
            )
    races: dict[tuple[int, int], list[tuple[int, str, str]]] = defaultdict(list)
    for row in results:
        if FIT_FIRST_YEAR <= _year(row) <= LAST_YEAR and row["positionText"].isdigit():
            races[(_year(row), int(row["round"]))].append(
                (int(row["positionNumber"]), row["driverId"], row["constructorId"])
            )

    events: list[Event] = []
    for weight, grouped in ((QUALIFYING_WEIGHT, sessions), (1.0, races)):
        for (year, _), entries in sorted(grouped.items()):
            order = [((car, year), (driver, year)) for _, driver, car in sorted(entries)]
            if len(order) >= 2:
                events.append((weight, order))
    return events


def fit(
    events: Sequence[Event], iterations: int = ITERATIONS
) -> tuple[dict[CarKey, float], dict[DriverKey, float]]:
    """Fit car and driver strengths to finishing orders.

    The model is Plackett-Luce with ``car + driver`` scores, where the choice of position
    ``j`` counts ``1 / j`` (who wins matters most), plus a ridge penalty on both kinds of
    strength and a smoothness penalty between a driver's consecutive seasons. The objective
    is concave, so there is one optimum; momentum gradient ascent reaches it.

    Args:
        events: ``(weight, [(car, driver), ...])`` with entries best first.
        iterations: Gradient steps.

    Returns:
        The fitted (uncentred) car and driver strengths.
    """
    cars = sorted({car for _, order in events for car, _ in order})
    drivers = sorted({driver for _, order in events for _, driver in order})
    car_index = {key: i for i, key in enumerate(cars)}
    driver_index = {key: i for i, key in enumerate(drivers)}
    indexed = [
        (weight, [car_index[c] for c, _ in order], [driver_index[d] for _, d in order])
        for weight, order in events
        if len(order) >= 2
    ]
    car_mass = [0.0] * len(cars)
    driver_mass = [0.0] * len(drivers)
    for weight, car_ids, driver_ids in indexed:
        for j, (c, d) in enumerate(zip(car_ids, driver_ids, strict=True)):
            car_mass[c] += weight / (j + 1)
            driver_mass[d] += weight / (j + 1)
    links = [
        (driver_index[a], driver_index[b], 1.0 / (b[1] - a[1]))
        for a, b in itertools.pairwise(drivers)
        if a[0] == b[0]
    ]

    car = [0.0] * len(cars)
    drv = [0.0] * len(drivers)
    car_velocity = [0.0] * len(cars)
    driver_velocity = [0.0] * len(drivers)
    for _ in range(iterations):
        car_grad = [-CAR_RIDGE * v for v in car]
        driver_grad = [-DRIVER_RIDGE * v for v in drv]
        for weight, car_ids, driver_ids in indexed:
            scores = [car[c] + drv[d] for c, d in zip(car_ids, driver_ids, strict=True)]
            top = max(scores)
            exps = [math.exp(s - top) for s in scores]
            n = len(scores)
            tail = [0.0] * n
            total = 0.0
            for i in range(n - 1, -1, -1):
                total += exps[i]
                tail[i] = total
            share = 0.0
            for k in range(n):
                stage = 1.0 / (k + 1) if k < n - 1 else 0.0
                if k < n - 1:
                    share += stage / tail[k]
                grad = weight * (stage - exps[k] * share)
                car_grad[car_ids[k]] += grad
                driver_grad[driver_ids[k]] += grad
        for i, j, link_weight in links:
            pull = SMOOTHNESS * link_weight * (drv[i] - drv[j])
            driver_grad[i] -= pull
            driver_grad[j] += pull
        for i in range(len(car)):
            car_velocity[i] = MOMENTUM * car_velocity[i] + STEP * car_grad[i] / (car_mass[i] + 5.0)
            car[i] += car_velocity[i]
        for i in range(len(drv)):
            driver_velocity[i] = MOMENTUM * driver_velocity[i] + STEP * driver_grad[i] / (
                driver_mass[i] + 5.0 + 2 * SMOOTHNESS
            )
            drv[i] += driver_velocity[i]
    return dict(zip(cars, car, strict=True)), dict(zip(drivers, drv, strict=True))


@dataclass
class Tallies:
    """Counts over the race results of the game's seasons."""

    races: Counter[int]
    car_starts: Counter[CarKey]
    driver_starts: Counter[tuple[str, CarKey]]
    engine_starts: dict[CarKey, Counter[str]]
    car_wins: Counter[CarKey]
    car_poles: Counter[CarKey]
    car_podiums: Counter[CarKey]
    driver_wins: Counter[tuple[str, CarKey]]
    driver_poles: Counter[tuple[str, CarKey]]
    driver_podiums: Counter[tuple[str, CarKey]]
    mechanical: Counter[CarKey]
    season_starts: Counter[int]
    season_mechanical: Counter[int]
    season_incidents: Counter[int]
    driver_incidents: Counter[str]
    driver_start_years: dict[str, list[int]]


def tally(races: Iterable[Row], results: Iterable[Row]) -> Tallies:
    """Count races, starts, results and retirements for 1980 to 2025.

    Args:
        races: Race rows.
        results: Race-result rows.

    Returns:
        The counts.
    """
    t = Tallies(
        races=Counter(_year(row) for row in races if _in_game(row)),
        car_starts=Counter(),
        driver_starts=Counter(),
        engine_starts=defaultdict(Counter),
        car_wins=Counter(),
        car_poles=Counter(),
        car_podiums=Counter(),
        driver_wins=Counter(),
        driver_poles=Counter(),
        driver_podiums=Counter(),
        mechanical=Counter(),
        season_starts=Counter(),
        season_mechanical=Counter(),
        season_incidents=Counter(),
        driver_incidents=Counter(),
        driver_start_years=defaultdict(list),
    )
    for row in results:
        if not _in_game(row):
            continue
        year = _year(row)
        car: CarKey = (row["constructorId"], year)
        seat = (row["driverId"], car)
        position = row["positionText"]
        if position == "1":
            t.car_wins[car] += 1
            t.driver_wins[seat] += 1
        if position in {"1", "2", "3"}:
            t.car_podiums[car] += 1
            t.driver_podiums[seat] += 1
        if row["polePosition"] == "true":
            t.car_poles[car] += 1
            t.driver_poles[seat] += 1
        if not is_start(row):
            continue
        t.car_starts[car] += 1
        t.driver_starts[seat] += 1
        t.engine_starts[car][row["engineManufacturerId"]] += 1
        t.season_starts[year] += 1
        t.driver_start_years[row["driverId"]].append(year)
        if position == "DNF":
            kind = classify_retirement(row["reasonRetired"])
            if kind == "mechanical":
                t.mechanical[car] += 1
                t.season_mechanical[year] += 1
            elif kind == "incident":
                t.season_incidents[year] += 1
                t.driver_incidents[row["driverId"]] += 1
    return t


def rosters(t: Tallies, fitted_drivers: Mapping[DriverKey, float]) -> dict[CarKey, list[str]]:
    """List each constructor-season's drivers, most starts first.

    Args:
        t: The counts.
        fitted_drivers: Fitted driver strengths; drivers without one are left out.

    Returns:
        Driver ids per car, for drivers with at least ``MIN_DRIVER_STARTS`` starts, ordered
        by starts (descending) then driver id.
    """
    by_car: dict[CarKey, list[tuple[int, str]]] = defaultdict(list)
    for (driver, car), starts in t.driver_starts.items():
        if starts >= MIN_DRIVER_STARTS and (driver, car[1]) in fitted_drivers:
            by_car[car].append((-starts, driver))
    return {car: [driver for _, driver in sorted(entries)] for car, entries in by_car.items()}


def eligible_cars(
    t: Tallies, fitted_cars: Mapping[CarKey, float], roster: Mapping[CarKey, list[str]]
) -> list[CarKey]:
    """Pick the constructor-seasons that ran a full season with two regular drivers.

    Args:
        t: The counts.
        fitted_cars: Fitted car strengths.
        roster: Driver ids per car.

    Returns:
        Cars with at least one start per race that year, a fitted strength and at least two
        roster drivers, sorted by year then constructor id.
    """
    return sorted(
        (
            car
            for car, starts in t.car_starts.items()
            if starts >= t.races[car[1]] and car in fitted_cars and len(roster.get(car, ())) >= 2
        ),
        key=lambda car: (car[1], car[0]),
    )


def centre(
    eligible: Sequence[CarKey],
    roster: Mapping[CarKey, list[str]],
    fitted_cars: Mapping[CarKey, float],
    fitted_drivers: Mapping[DriverKey, float],
) -> tuple[dict[CarKey, float], dict[DriverKey, float]]:
    """Put cars and drivers on a common per-season scale.

    Args:
        eligible: The game's cars.
        roster: Driver ids per car; the first two are the main drivers.
        fitted_cars: Fitted car strengths.
        fitted_drivers: Fitted driver strengths.

    Returns:
        Car strengths (mean 0 per season) and the ratings of every roster driver (mean 0 over
        each season's main drivers), both scaled by ``SHARPNESS``.
    """
    cars: dict[CarKey, float] = {}
    drivers: dict[DriverKey, float] = {}
    for year in sorted({car[1] for car in eligible}):
        field = [car for car in eligible if car[1] == year]
        car_mean = statistics.fmean(fitted_cars[car] for car in field)
        driver_mean = statistics.fmean(
            fitted_drivers[(driver, year)] for car in field for driver in roster[car][:2]
        )
        for car in field:
            cars[car] = SHARPNESS * (fitted_cars[car] - car_mean)
            for driver in roster[car]:
                drivers[(driver, year)] = SHARPNESS * (fitted_drivers[(driver, year)] - driver_mean)
    return cars, drivers


def engine_ids(t: Tallies, eligible: Iterable[CarKey]) -> dict[CarKey, tuple[str, str]]:
    """Find each car's engine.

    Args:
        t: The counts.
        eligible: The game's cars.

    Returns:
        ``(engine id, badge id)`` per car: the badge is the manufacturer with the most starts
        (ties: alphabetically first) and the engine id is the badge after ``ENGINE_ALIASES``.
    """
    out: dict[CarKey, tuple[str, str]] = {}
    for car in eligible:
        badge = min(t.engine_starts[car].items(), key=lambda kv: (-kv[1], kv[0]))[0]
        out[car] = (ENGINE_ALIASES.get(badge, badge), badge)
    return out


def engine_values(
    cars: Mapping[CarKey, float],
    engines: Mapping[CarKey, tuple[str, str]],
    corrections: Iterable[Correction],
) -> dict[EngineKey, float]:
    """Rate every engine-season from the cars that used it.

    Args:
        cars: Car strengths.
        engines: ``(engine id, badge)`` per car.
        corrections: Report-based adjustments.

    Returns:
        Per ``(engine id, year)``: the mean strength of its best two cars (or its only car),
        times 2/3 (or 1/2 for a single team), plus its correction.

    Raises:
        DataError: If a correction names an engine-season that does not exist.
    """
    users: dict[EngineKey, list[float]] = defaultdict(list)
    for car, (engine, _) in engines.items():
        users[(engine, car[1])].append(cars[car])
    values: dict[EngineKey, float] = {}
    for key, strengths in users.items():
        best = sorted(strengths, reverse=True)[:2]
        values[key] = statistics.fmean(best) * (2 / 3 if len(strengths) >= 2 else 1 / 2)
    for correction in corrections:
        key = (correction.engine_id, correction.year)
        if key not in values:
            raise DataError(f"correction for unknown engine-season {key}")
        values[key] += correction.delta
    return values


def reliability(t: Tallies, eligible: Iterable[CarKey]) -> dict[CarKey, float]:
    """Rate each car's mechanical reliability against its own era.

    Args:
        t: The counts.
        eligible: The game's cars.

    Returns:
        Mechanical retirements relative to the season's rate, shrunk towards 1 (average);
        lower is better.
    """
    out: dict[CarKey, float] = {}
    for car in eligible:
        year = car[1]
        season_rate = t.season_mechanical[year] / t.season_starts[year]
        expected = t.car_starts[car] * season_rate
        out[car] = (t.mechanical[car] + PSEUDO_COUNT) / (expected + PSEUDO_COUNT)
    return out


def incident_ratios(t: Tallies) -> dict[str, float]:
    """Rate how often each driver crashes out, over his whole career, against his eras.

    Args:
        t: The counts.

    Returns:
        Incident retirements relative to what an average driver would have had in the same
        seasons, shrunk towards 1; lower is better.
    """
    out: dict[str, float] = {}
    for driver, years in t.driver_start_years.items():
        expected = sum(t.season_incidents[y] / t.season_starts[y] for y in years)
        out[driver] = (t.driver_incidents[driver] + PSEUDO_COUNT) / (expected + PSEUDO_COUNT)
    return out


def pit_values(
    pit_stops: Iterable[Row], eligible: Iterable[CarKey]
) -> dict[CarKey, tuple[float, int]]:
    """Rate pit crews from pit-stop times, within each season.

    Args:
        pit_stops: Pit-stop rows (timing exists from 1994).
        eligible: The game's cars.

    Returns:
        ``(z, rank)`` for every rated car: ``z`` is minus the standardised median gap to each
        race's median stop (clamped to ``±PIT_Z_CAP``), ``rank`` its 1-based place in the
        season. Cars without enough timed races, and seasons with too few rated teams, are
        left out.
    """
    by_race: dict[tuple[int, int], list[tuple[str, float]]] = defaultdict(list)
    for row in pit_stops:
        if _in_game(row) and row["timeMillis"]:
            by_race[(_year(row), int(row["round"]))].append(
                (row["constructorId"], int(row["timeMillis"]) / 1000)
            )
    gaps: dict[CarKey, list[float]] = defaultdict(list)
    for (year, _), stops in sorted(by_race.items()):
        median = statistics.median(time for _, time in stops)
        kept: dict[str, list[float]] = defaultdict(list)
        for constructor, time in stops:
            if time <= median + PIT_SLOW_STOP_SECONDS:
                kept[constructor].append(time)
        for constructor, times in kept.items():
            gaps[(constructor, year)].append(statistics.median(times) - median)

    eligible = list(eligible)
    out: dict[CarKey, tuple[float, int]] = {}
    for year in sorted({car[1] for car in eligible}):
        rated = [
            car for car in eligible if car[1] == year and len(gaps.get(car, ())) >= PIT_MIN_RACES
        ]
        if len(rated) < PIT_MIN_TEAMS:
            continue
        values = {car: statistics.median(gaps[car]) for car in rated}
        mean = statistics.fmean(values.values())
        spread = statistics.pstdev(values.values())
        z = {
            car: max(-PIT_Z_CAP, min(PIT_Z_CAP, -(value - mean) / spread))
            for car, value in values.items()
        }
        ranked = sorted(rated, key=lambda car: (-z[car], car[0]))
        for rank, car in enumerate(ranked, start=1):
            out[car] = (z[car], rank)
    return out


def _r(value: float) -> float:
    return round(value, 3) + 0.0  # + 0.0 turns -0.0 into 0.0


def _f(value: float) -> str:
    return f"{_r(value):.3f}"


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _names(rows: Iterable[Row]) -> dict[str, str]:
    return {row["id"]: row["name"] for row in rows}


def _positions(rows: Iterable[Row], id_column: str) -> dict[tuple[str, int], int]:
    out: dict[tuple[str, int], int] = {}
    for row in rows:
        if row["positionNumber"]:
            key = (row[id_column], _year(row))
            position = int(row["positionNumber"])
            out[key] = min(position, out.get(key, position))
    return out


def build(
    tables: Tables, corrections: Sequence[Correction], iterations: int = ITERATIONS
) -> tuple[list[OutputRow], list[OutputRow]]:
    """Turn the F1DB tables into the bundled car and driver rows.

    Args:
        tables: Source rows by the keys of ``TABLE_FILES``.
        corrections: Report-based engine adjustments.
        iterations: Gradient steps of the strength fit.

    Returns:
        The car rows (sorted by year then constructor) and the driver rows (sorted by year,
        constructor, then roster order).
    """
    fitted_cars, fitted_drivers = fit(
        fit_events(tables["results"], tables["qualifying"]), iterations
    )
    t = tally(tables["races"], tables["results"])
    roster = rosters(t, fitted_drivers)
    eligible = eligible_cars(t, fitted_cars, roster)
    cars, drivers = centre(eligible, roster, fitted_cars, fitted_drivers)
    engines = engine_ids(t, eligible)
    engine = engine_values(cars, engines, corrections)
    reliable = reliability(t, eligible)
    incidents = incident_ratios(t)
    pits = pit_values(tables["pit_stops"], eligible)

    constructor_names = _names(tables["constructors"])
    engine_names = _names(tables["engines"])
    driver_names = _names(tables["drivers"])
    chassis_names = _names(tables["chassis"])
    chassis_by_car: dict[CarKey, set[str]] = defaultdict(set)
    for row in tables["entrant_chassis"]:
        chassis_by_car[(row["constructorId"], _year(row))].add(chassis_names[row["chassisId"]])
    constructor_positions = _positions(tables["constructor_standings"], "constructorId")
    driver_positions = _positions(tables["driver_standings"], "driverId")

    engine_users: dict[EngineKey, list[CarKey]] = defaultdict(list)
    for car, (engine_id, _) in engines.items():
        engine_users[(engine_id, car[1])].append(car)

    car_rows: list[OutputRow] = []
    driver_rows: list[OutputRow] = []
    for car in eligible:
        constructor, year = car
        engine_id, badge = engines[car]
        engine_key = (engine_id, year)
        pit_z, pit_rank = pits.get(car, (0.0, 0))
        car_value = _r(cars[car])
        engine_value = _r(engine[engine_key])
        pit_value = _r(PIT_WEIGHT * pit_z)
        position = constructor_positions.get(car)
        car_rows.append(
            {
                "constructor_id": constructor,
                "year": str(year),
                "name": constructor_names[constructor],
                "chassis_name": " / ".join(sorted(chassis_by_car[car])),
                "engine_id": engine_id,
                "engine_name": engine_names[engine_id],
                "engine_badge": engine_names[badge],
                "car": _f(car_value),
                "engine": _f(engine_value),
                "chassis": _f(car_value - engine_value - pit_value),
                "pit": _f(pit_value),
                "pit_rated": _flag(car in pits),
                "pit_rank": str(pit_rank) if car in pits else "",
                "reliability": _f(reliable[car]),
                "races": str(t.races[year]),
                "starts": str(t.car_starts[car]),
                "wins": str(t.car_wins[car]),
                "poles": str(t.car_poles[car]),
                "podiums": str(t.car_podiums[car]),
                "mechanical_retirements": str(t.mechanical[car]),
                "engine_wins": str(sum(t.car_wins[user] for user in engine_users[engine_key])),
                "engine_teams": str(len(engine_users[engine_key])),
                "championship_position": "" if position is None else str(position),
                "rollable": _flag(t.car_wins[car] > 0),
            }
        )
        for index, driver in enumerate(roster[car]):
            seat = (driver, car)
            driver_position = driver_positions.get((driver, year))
            driver_rows.append(
                {
                    "driver_id": driver,
                    "name": driver_names[driver],
                    "year": str(year),
                    "constructor_id": constructor,
                    "rating": _f(drivers[(driver, year)]),
                    "incident": _f(incidents[driver]),
                    "starts": str(t.driver_starts[seat]),
                    "wins": str(t.driver_wins[seat]),
                    "poles": str(t.driver_poles[seat]),
                    "podiums": str(t.driver_podiums[seat]),
                    "championship_position": (
                        "" if driver_position is None else str(driver_position)
                    ),
                    "main": _flag(index < 2),
                }
            )
    return car_rows, driver_rows


def validate(cars: Sequence[OutputRow], drivers: Sequence[OutputRow]) -> None:
    """Check the built rows are consistent enough for the game to use.

    Args:
        cars: Car rows from :func:`build`.
        drivers: Driver rows from :func:`build`.

    Raises:
        DataError: On a duplicate car or card, a driver without a car, a car without exactly
            two main drivers, or parts that do not add up to the car.
    """
    car_keys = Counter((row["constructor_id"], row["year"]) for row in cars)
    if any(count > 1 for count in car_keys.values()):
        raise DataError("duplicate constructor-seasons")
    cards = Counter((row["driver_id"], row["year"], row["constructor_id"]) for row in drivers)
    if any(count > 1 for count in cards.values()):
        raise DataError("duplicate driver cards")
    mains: Counter[tuple[str, str]] = Counter()
    for row in drivers:
        key = (row["constructor_id"], row["year"])
        if key not in car_keys:
            raise DataError(f"driver {row['driver_id']} has no car {key}")
        mains[key] += row["main"] == "true"
    wrong = [key for key in car_keys if mains[key] != 2]
    if wrong:
        raise DataError(f"cars without exactly two main drivers: {wrong[:5]}")
    for row in cars:
        parts = float(row["engine"]) + float(row["chassis"]) + float(row["pit"])
        if abs(parts - float(row["car"])) > 1e-6:
            raise DataError(f"parts do not add up for {row['constructor_id']} {row['year']}")


def check_sources(tables: Tables) -> None:
    """Check the source tables are the pinned release's.

    Args:
        tables: Source rows by the keys of ``TABLE_FILES``.

    Raises:
        DataError: If a table does not have the expected number of rows for 1975 to 2025.
    """

    def count(name: str) -> int:
        return sum(1 for row in tables[name] if FIT_FIRST_YEAR <= _year(row) <= LAST_YEAR)

    actual = (count("races"), count("results"), count("qualifying"))
    expected = (EXPECTED_SOURCE_RACES, EXPECTED_SOURCE_RESULTS, EXPECTED_SOURCE_QUALIFYING)
    if actual != expected:
        raise DataError(f"expected races, results, qualifying {expected}, got {actual}")


def check_expected(cars: Sequence[OutputRow], drivers: Sequence[OutputRow]) -> None:
    """Check the output matches what the pinned release is known to produce.

    Args:
        cars: Car rows from :func:`build`.
        drivers: Driver rows from :func:`build`.

    Raises:
        DataError: If a count or a pinned rating is off.
    """
    counts = (
        len(cars),
        sum(row["rollable"] == "true" for row in cars),
        len(drivers),
        len({row["year"] for row in cars}),
        len({(row["engine_id"], row["year"]) for row in cars}),
        sum(row["pit_rated"] == "true" for row in cars),
    )
    expected = (
        EXPECTED_CARS,
        EXPECTED_ROLLABLE,
        EXPECTED_DRIVERS,
        EXPECTED_SEASONS,
        EXPECTED_ENGINE_SEASONS,
        EXPECTED_PIT_RATED,
    )
    if counts != expected:
        raise DataError(f"expected counts {expected}, got {counts}")
    car_values = {f"{row['constructor_id']}:{row['year']}": float(row["car"]) for row in cars}
    driver_values = {
        f"{row['driver_id']}:{row['year']}:{row['constructor_id']}": float(row["rating"])
        for row in drivers
    }
    for values, pins in ((car_values, PINNED_CARS), (driver_values, PINNED_DRIVERS)):
        for key, pinned in pins.items():
            if abs(values[key] - pinned) > PIN_TOLERANCE:
                raise DataError(f"{key} is {values[key]}, expected {pinned}")


def _download() -> Path:
    path = CACHE_DIR / "f1db-csv.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {URL}")
        with urllib.request.urlopen(URL, timeout=120) as response:
            path.write_bytes(response.read())
    data = path.read_bytes()
    if len(data) != ZIP_SIZE or hashlib.sha256(data).hexdigest() != ZIP_SHA256:
        raise DataError(f"{path} is not the pinned F1DB {RELEASE} release; delete it and retry")
    return path


def read_tables(zip_path: Path) -> dict[str, list[dict[str, str]]]:
    """Read every needed table from the F1DB zip.

    Args:
        zip_path: The downloaded ``f1db-csv.zip``.

    Returns:
        Rows by the keys of ``TABLE_FILES``.
    """
    with zipfile.ZipFile(zip_path) as archive:
        tables = {}
        for key, name in TABLE_FILES.items():
            with archive.open(name) as raw:
                tables[key] = list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8")))
    return tables


def _write(path: Path, columns: Sequence[str], rows: Iterable[OutputRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> None:
    """Download F1DB, build the dataset and write the bundled CSVs.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.
    """
    parser = argparse.ArgumentParser(description="Build the bundled Clean Sweep dataset.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    tables = read_tables(_download())
    check_sources(tables)
    with CORRECTIONS_FILE.open(encoding="utf-8", newline="") as file:
        corrections = parse_corrections(csv.DictReader(file))
    cars, drivers = build(tables, corrections)
    validate(cars, drivers)
    check_expected(cars, drivers)
    _write(args.output / "cars.csv", CAR_COLUMNS, cars)
    _write(args.output / "drivers.csv", DRIVER_COLUMNS, drivers)
    print(f"Wrote {len(cars)} cars and {len(drivers)} driver cards to {args.output}")


if __name__ == "__main__":
    main()
