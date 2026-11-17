import csv
import io
import statistics
import zipfile
from pathlib import Path

import pytest

from tools.build_sweep_dataset import (
    CAR_COLUMNS,
    DRIVER_COLUMNS,
    PIT_WEIGHT,
    PSEUDO_COUNT,
    QUALIFYING_WEIGHT,
    SHARPNESS,
    TABLE_FILES,
    Correction,
    DataError,
    OutputRow,
    Tier,
    build,
    career_ratings,
    centre,
    check_expected,
    check_sources,
    classify_retirement,
    eligible_cars,
    engine_ids,
    engine_values,
    fit,
    fit_events,
    incident_ratios,
    is_start,
    parse_corrections,
    parse_tiers,
    pit_values,
    poll_floor,
    read_tables,
    reliability,
    rosters,
    tally,
    validate,
)


def result(**overrides: object) -> dict[str, str]:
    row = {
        "year": "1980",
        "round": "1",
        "positionNumber": "1",
        "positionText": "1",
        "driverId": "a1",
        "constructorId": "a",
        "engineManufacturerId": "ford",
        "reasonRetired": "",
        "polePosition": "false",
    }
    return row | {key: str(value) for key, value in overrides.items()}


def race(year: int = 1980) -> dict[str, str]:
    return {"year": str(year)}


def pit(year: int, rnd: int, constructor: str, seconds: float) -> dict[str, str]:
    return {
        "year": str(year),
        "round": str(rnd),
        "constructorId": constructor,
        "timeMillis": str(round(seconds * 1000)),
    }


# A tiny world: 1980, three races, teams a to e with two drivers each, finishing in order.
TEAMS = ("a", "b", "c", "d", "e")
ROUNDS = (1, 2, 3)


def world_results() -> list[dict[str, str]]:
    rows = []
    for rnd in ROUNDS:
        for place, (team, seat) in enumerate(((t, s) for t in TEAMS for s in (1, 2)), start=1):
            rows.append(
                result(
                    round=rnd,
                    positionNumber=place,
                    positionText=place,
                    driverId=f"{team}{seat}",
                    constructorId=team,
                    engineManufacturerId="ford" if team != "c" else "playlife",
                    polePosition="true" if place == 1 else "false",
                )
            )
    return rows


def world_tables() -> dict[str, list[dict[str, str]]]:
    results = world_results()
    qualifying = [
        {
            "year": row["year"],
            "round": row["round"],
            "positionNumber": row["positionNumber"],
            "driverId": row["driverId"],
            "constructorId": row["constructorId"],
        }
        for row in results
    ]
    return {
        "races": [race() for _ in ROUNDS],
        "results": results,
        "qualifying": qualifying,
        "pit_stops": [],
        "drivers": [{"id": f"{t}{s}", "name": f"Driver {t}{s}"} for t in TEAMS for s in (1, 2)],
        "constructors": [{"id": t, "name": f"Team {t.upper()}"} for t in TEAMS],
        "engines": [
            {"id": "ford", "name": "Ford"},
            {"id": "playlife", "name": "Playlife"},
            {"id": "renault", "name": "Renault"},
        ],
        "chassis": [{"id": "a-1", "name": "A1"}, {"id": "a-1b", "name": "A1B"}],
        "entrant_chassis": [
            {"year": "1980", "constructorId": "a", "chassisId": "a-1b"},
            {"year": "1980", "constructorId": "a", "chassisId": "a-1"},
        ],
        "constructor_standings": [
            {"year": "1980", "constructorId": "a", "positionNumber": "1"},
            {"year": "1980", "constructorId": "b", "positionNumber": ""},
        ],
        "driver_standings": [{"year": "1980", "driverId": "a1", "positionNumber": "1"}],
    }


class TestRules:
    @pytest.mark.parametrize("text", ["DNQ", "DNPQ", "DNS", "DNP", "EX"])
    def test_non_starts(self, text: str) -> None:
        assert not is_start(result(positionText=text))

    @pytest.mark.parametrize("text", ["1", "DNF", "DSQ", "NC"])
    def test_starts(self, text: str) -> None:
        assert is_start(result(positionText=text))

    @pytest.mark.parametrize(
        ("reason", "kind"),
        [
            ("Collision", "incident"),
            ("Spun off", "incident"),
            ("Withdrew", "ignored"),
            ("Car raced by Jarier", "ignored"),
            ("Engine", "mechanical"),
            ("Gearbox", "mechanical"),
            ("Puncture", "mechanical"),
        ],
    )
    def test_retirement_classes(self, reason: str, kind: str) -> None:
        assert classify_retirement(reason) == kind

    def test_duplicate_corrections_are_rejected(self) -> None:
        row = {"engine_id": "ford", "year": "1982", "delta": "-0.5", "source": "s", "note": "n"}

        assert parse_corrections([row]) == [Correction("ford", 1982, -0.5, "s", "n")]
        with pytest.raises(DataError, match="more than once"):
            parse_corrections([row, row])

    def test_shipped_corrections_parse(self) -> None:
        path = Path(__file__).resolve().parents[2] / "tools" / "sweep_corrections.csv"
        with path.open(encoding="utf-8", newline="") as file:
            corrections = parse_corrections(csv.DictReader(file))

        assert len(corrections) == 11
        assert all(c.source.startswith("https://en.wikipedia.org/wiki/") for c in corrections)

    def test_tiers(self) -> None:
        row = {"driver_id": "a1", "rank": "3", "source": "s", "note": "n"}

        assert parse_tiers([row]) == [Tier("a1", 3, "s", "n")]
        with pytest.raises(DataError, match="more than once"):
            parse_tiers([row, row])
        with pytest.raises(DataError, match="start at 1"):
            parse_tiers([row | {"rank": "0"}])

    def test_shipped_tiers_parse(self) -> None:
        path = Path(__file__).resolve().parents[2] / "tools" / "sweep_driver_tiers.csv"
        with path.open(encoding="utf-8", newline="") as file:
            tiers = parse_tiers(csv.DictReader(file))

        assert len(tiers) == 30
        assert all(t.source.startswith("https://www.autosport.com/") for t in tiers)
        assert [t.driver_id for t in tiers if t.rank <= 5] == [
            "ayrton-senna",
            "lewis-hamilton",
            "michael-schumacher",
            "max-verstappen",
        ]

    @pytest.mark.parametrize(
        ("rank", "floor"), [(1, 2.8), (5, 2.8), (6, 2.2), (15, 2.2), (30, 1.6), (50, 1.1)]
    )
    def test_poll_floor(self, rank: int, floor: float) -> None:
        assert poll_floor(rank) == floor

    def test_no_floor_below_the_poll(self) -> None:
        assert poll_floor(51) == float("-inf")

    def test_career_ratings(self) -> None:
        def card(driver: str, rating: float) -> OutputRow:
            return {"driver_id": driver, "rating": str(rating)}

        rows = [card("x", r) for r in (1.0, 0.5, 0.0, -1.0)] + [card("y", 0.2), card("z", 0.4)]
        tiers = [Tier("y", 3, "s", "n"), Tier("z", 60, "s", "n")]

        career = career_ratings(rows, tiers)

        assert career == {"x": pytest.approx(0.5), "y": 2.8, "z": pytest.approx(0.4)}
        with pytest.raises(DataError, match="match no driver"):
            career_ratings(rows, [Tier("nobody", 1, "s", "n")])


class TestFitEvents:
    def test_orders_qualifying_then_races(self) -> None:
        results = [
            result(positionNumber=2, positionText=2, driverId="x"),
            result(positionNumber=1, positionText=1, driverId="y"),
            result(positionNumber="", positionText="DNF", driverId="z"),
        ]
        qualifying = [
            {
                "year": "1980",
                "round": "1",
                "positionNumber": "2",
                "driverId": "y",
                "constructorId": "a",
            },
            {
                "year": "1980",
                "round": "1",
                "positionNumber": "1",
                "driverId": "x",
                "constructorId": "a",
            },
            {
                "year": "1980",
                "round": "1",
                "positionNumber": "",
                "driverId": "z",
                "constructorId": "a",
            },
        ]

        events = fit_events(results, qualifying)

        assert events == [
            (QUALIFYING_WEIGHT, [(("a", 1980), ("x", 1980)), (("a", 1980), ("y", 1980))]),
            (1.0, [(("a", 1980), ("y", 1980)), (("a", 1980), ("x", 1980))]),
        ]

    def test_skips_old_seasons_and_single_entries(self) -> None:
        results = [
            result(year=1974, driverId="old"),
            result(year=1974, positionNumber=2, positionText=2, driverId="older"),
            result(year=1981, driverId="alone"),
        ]

        assert fit_events(results, []) == []


class TestFit:
    def test_the_car_that_always_wins_is_strongest(self) -> None:
        order = [(("fast", 1990), ("d1", 1990)), (("mid", 1990), ("d2", 1990))]
        order.append((("slow", 1990), ("d3", 1990)))
        cars, _ = fit([(1.0, order)] * 5, iterations=300)

        assert cars[("fast", 1990)] > cars[("mid", 1990)] > cars[("slow", 1990)]

    def test_identical_entrants_get_equal_values(self) -> None:
        first = [(("a", 1990), ("d1", 1990)), (("b", 1990), ("d2", 1990))]
        second = [(("b", 1990), ("d2", 1990)), (("a", 1990), ("d1", 1990))]
        cars, drivers = fit([(1.0, first), (1.0, second)], iterations=300)

        assert cars[("a", 1990)] == pytest.approx(cars[("b", 1990)])
        assert drivers[("d1", 1990)] == pytest.approx(drivers[("d2", 1990)])

    def test_event_order_does_not_matter(self) -> None:
        events = fit_events(world_results(), [])
        events.append((1.0, [(("c", 1980), ("c1", 1980)), (("a", 1980), ("a2", 1980))]))
        forward, _ = fit(events, iterations=200)
        backward, _ = fit(events[::-1], iterations=200)

        for key, value in forward.items():
            assert backward[key] == pytest.approx(value, abs=1e-9)

    def test_consecutive_seasons_of_a_driver_are_pulled_together(self) -> None:
        won = [(("a", 1990), ("star", 1990)), (("a", 1990), ("x", 1990))]
        tie = [(("b", 1991), ("star", 1991)), (("b", 1991), ("z", 1991))]
        _, drivers = fit([(1.0, won)] * 3 + [(1.0, tie), (1.0, tie[::-1])], iterations=300)

        assert drivers[("star", 1991)] > drivers[("z", 1991)]


class TestTallyAndRosters:
    def test_counts(self) -> None:
        results = [
            result(positionText="1", polePosition="true"),
            result(round=2, positionText="3"),
            result(round=3, positionText="DNF", reasonRetired="Engine"),
            result(round=4, positionText="DNF", reasonRetired="Collision"),
            result(round=5, positionText="DNF", reasonRetired="Withdrew"),
            result(round=6, positionText="DNQ"),
            result(year=2026, positionText="1"),
        ]

        t = tally([race(), race(), race(2026)], results)

        car = ("a", 1980)
        assert t.races[1980] == 2
        assert 2026 not in t.races
        assert t.car_starts[car] == 5
        assert t.car_wins[car] == 1
        assert t.car_podiums[car] == 2
        assert t.car_poles[car] == 1
        assert t.mechanical[car] == 1
        assert t.season_incidents[1980] == 1
        assert t.driver_incidents["a1"] == 1
        assert t.driver_start_years["a1"] == [1980] * 5

    def test_roster_order_and_minimum_starts(self) -> None:
        results = [result(round=r, driverId="z") for r in range(5)]
        results += [result(round=r, driverId="y") for r in range(3)]
        results += [result(round=r, driverId="x") for r in range(3)]
        results += [result(round=r, driverId="short") for r in range(2)]
        results += [result(round=r, driverId="unfitted") for r in range(4)]
        fitted = {(d, 1980): 0.0 for d in ("x", "y", "z", "short")}

        roster = rosters(tally([], results), fitted)

        assert roster[("a", 1980)] == ["z", "x", "y"]

    def test_eligibility(self) -> None:
        results = [result(round=r, driverId=f"a{r % 2}") for r in range(4)]
        results += [result(round=r, driverId="b1", constructorId="b") for r in range(4)]
        results += [result(round=1, driverId="c1", constructorId="c")]
        t = tally([race()] * 4, results)
        roster = {("a", 1980): ["a0", "a1"], ("b", 1980): ["b1"], ("c", 1980): ["c1", "c2"]}
        fitted = {("a", 1980): 0.0, ("b", 1980): 0.0, ("c", 1980): 0.0}

        assert eligible_cars(t, fitted, roster) == [("a", 1980)]
        assert eligible_cars(t, {}, roster) == []


class TestValues:
    def test_centre(self) -> None:
        eligible = [("a", 1980), ("b", 1980), ("a", 1981)]
        roster = {("a", 1980): ["x", "y", "r"], ("b", 1980): ["z", "w"], ("a", 1981): ["x", "q"]}
        fitted_cars = {("a", 1980): 3.0, ("b", 1980): 1.0, ("a", 1981): 5.0}
        fitted_drivers = {
            ("x", 1980): 1.0,
            ("y", 1980): 2.0,
            ("r", 1980): 9.0,
            ("z", 1980): 3.0,
            ("w", 1980): 4.0,
            ("x", 1981): 1.0,
            ("q", 1981): 3.0,
        }

        cars, drivers = centre(eligible, roster, fitted_cars, fitted_drivers)

        assert cars == {("a", 1980): SHARPNESS, ("b", 1980): -SHARPNESS, ("a", 1981): 0.0}
        assert drivers[("x", 1980)] == pytest.approx(SHARPNESS * -1.5)
        assert drivers[("r", 1980)] == pytest.approx(SHARPNESS * 6.5)  # reserves not in mean
        assert drivers[("q", 1981)] == pytest.approx(SHARPNESS)

    def test_engine_ids_use_aliases_and_alphabetical_ties(self) -> None:
        results = [result(engineManufacturerId="tag-heuer"), result(engineManufacturerId="bmw")]
        results += [result(constructorId="b", engineManufacturerId="playlife")]
        t = tally([], results)

        engines = engine_ids(t, [("a", 1980), ("b", 1980)])

        assert engines == {("a", 1980): ("bmw", "bmw"), ("b", 1980): ("renault", "playlife")}

    def test_engine_values(self) -> None:
        cars = {("a", 1990): 3.0, ("b", 1990): 1.0, ("c", 1990): -5.0, ("d", 1990): 2.0}
        engines = {
            ("a", 1990): ("ford", "ford"),
            ("b", 1990): ("ford", "ford"),
            ("c", 1990): ("ford", "ford"),
            ("d", 1990): ("honda", "honda"),
        }

        values = engine_values(cars, engines, [Correction("honda", 1990, 0.25, "s", "n")])

        assert values[("ford", 1990)] == pytest.approx(2.0 * 2 / 3)  # best two of three
        assert values[("honda", 1990)] == pytest.approx(1.0 + 0.25)  # single team: half
        with pytest.raises(DataError, match="unknown engine-season"):
            engine_values(cars, engines, [Correction("honda", 1991, 0.25, "s", "n")])

    def test_reliability_and_incidents(self) -> None:
        results = [result(round=r, driverId="a1") for r in range(8)]
        results += [result(round=r, driverId="b1", constructorId="b") for r in range(8)]
        results[0] |= {"positionText": "DNF", "reasonRetired": "Engine"}
        results[1] |= {"positionText": "DNF", "reasonRetired": "Spun off"}
        t = tally([], results)

        rel = reliability(t, [("a", 1980), ("b", 1980)])
        inc = incident_ratios(t)

        assert rel[("a", 1980)] == pytest.approx((1 + PSEUDO_COUNT) / (0.5 + PSEUDO_COUNT))
        assert rel[("b", 1980)] == pytest.approx(PSEUDO_COUNT / (0.5 + PSEUDO_COUNT))
        assert inc["a1"] == pytest.approx((1 + PSEUDO_COUNT) / (0.5 + PSEUDO_COUNT))
        assert inc["b1"] == pytest.approx(PSEUDO_COUNT / (0.5 + PSEUDO_COUNT))

    def test_pit_values(self) -> None:
        teams = ["p", "q", "r", "s", "t"]
        rows = [pit(2000, rnd, team, 20 + i) for rnd in range(5) for i, team in enumerate(teams)]
        rows.append(pit(2000, 0, "p", 60.0))  # a slow stop, dropped
        rows += [pit(2000, rnd, "u", 20.0) for rnd in range(4)]  # too few races
        rows += [pit(2001, rnd, team, 20.0) for rnd in range(5) for team in teams[:4]]
        eligible = [(team, 2000) for team in [*teams, "u"]] + [(t, 2001) for t in teams[:4]]

        values = pit_values(rows, eligible)

        z = [values[(team, 2000)][0] for team in teams]
        assert z == pytest.approx([2**0.5, 2**0.5 / 2, 0.0, -(2**0.5) / 2, -(2**0.5)])
        assert [values[(team, 2000)][1] for team in teams] == [1, 2, 3, 4, 5]
        assert ("u", 2000) not in values
        assert not any(year == 2001 for _, year in values)  # only four rated teams

    def test_pit_z_is_capped(self) -> None:
        times = [20.0] * 9 + [26.0]
        teams = [f"t{i}" for i in range(10)]
        rows = [
            pit(2000, rnd, team, t)
            for rnd in range(5)
            for team, t in zip(teams, times, strict=True)
        ]

        values = pit_values(rows, [(team, 2000) for team in teams])

        assert values[("t9", 2000)][0] == -2.0


@pytest.fixture(scope="module")
def built() -> tuple[list[OutputRow], list[OutputRow]]:
    return build(world_tables(), [], iterations=200)


class TestBuild:
    def test_shapes(self, built: tuple[list[OutputRow], list[OutputRow]]) -> None:
        cars, drivers = built

        assert [row["constructor_id"] for row in cars] == list(TEAMS)
        assert len(drivers) == 10
        assert tuple(cars[0]) == CAR_COLUMNS
        assert tuple(drivers[0]) == DRIVER_COLUMNS
        validate(cars, drivers)

    def test_car_facts(self, built: tuple[list[OutputRow], list[OutputRow]]) -> None:
        cars, _ = built
        a, b, c = cars[:3]

        assert a["name"] == "Team A"
        assert a["chassis_name"] == "A1 / A1B"
        assert (a["wins"], a["poles"], a["podiums"], a["races"], a["starts"]) == (
            "3",
            "3",
            "6",
            "3",
            "6",
        )
        assert a["rollable"] == "true"
        assert b["rollable"] == "false"
        assert a["championship_position"] == "1"
        assert b["championship_position"] == ""
        assert (c["engine_id"], c["engine_name"], c["engine_badge"]) == (
            "renault",
            "Renault",
            "Playlife",
        )
        assert (a["engine_wins"], a["engine_teams"]) == ("3", "4")
        assert a["pit_rated"] == "false"
        assert a["pit"] == "0.000"
        assert a["pit_rank"] == ""
        assert float(a["car"]) > float(b["car"]) > float(c["car"])
        assert statistics.fmean(float(row["car"]) for row in cars) == pytest.approx(0, abs=1e-3)

    def test_driver_facts(self, built: tuple[list[OutputRow], list[OutputRow]]) -> None:
        _, drivers = built
        first = drivers[0]

        assert (first["driver_id"], first["name"], first["main"]) == ("a1", "Driver a1", "true")
        assert (first["wins"], first["poles"], first["starts"]) == ("3", "3", "3")
        assert first["championship_position"] == "1"
        assert drivers[1]["championship_position"] == ""

    def test_career_column(self, built: tuple[list[OutputRow], list[OutputRow]]) -> None:
        _, drivers = built
        assert all(row["career"] == row["rating"] for row in drivers)  # one season each

        weakest = min(drivers, key=lambda row: float(row["rating"]))["driver_id"]
        best = max(drivers, key=lambda row: float(row["rating"]))
        tiers = [Tier(weakest, 1, "s", "n"), Tier(best["driver_id"], 50, "s", "n")]
        _, raised = build(world_tables(), [], tiers, iterations=200)
        careers = {row["driver_id"]: row["career"] for row in raised}
        assert careers[weakest] == "2.800"
        assert careers[best["driver_id"]] == best["rating"]  # already above the floor

    def test_parts_add_up_with_pit_and_corrections(self) -> None:
        tables = world_tables()
        tables["pit_stops"] = [
            pit(1980, rnd, team, 20 + i) for rnd in range(5) for i, team in enumerate(TEAMS)
        ]
        cars, drivers = build(tables, [Correction("ford", 1980, 0.5, "s", "n")], iterations=50)

        validate(cars, drivers)
        a = cars[0]
        assert a["pit_rated"] == "true"
        assert a["pit_rank"] == "1"
        assert float(a["pit"]) == pytest.approx(PIT_WEIGHT * 2**0.5, abs=1e-3)


class TestChecks:
    def test_validate_errors(self) -> None:
        cars, drivers = build(world_tables(), [], iterations=20)

        with pytest.raises(DataError, match="duplicate constructor"):
            validate([*cars, cars[0]], drivers)
        with pytest.raises(DataError, match="duplicate driver"):
            validate(cars, [*drivers, drivers[0]])
        with pytest.raises(DataError, match="has no car"):
            validate(cars[1:], drivers)
        with pytest.raises(DataError, match="two main"):
            validate(cars, drivers[1:])
        with pytest.raises(DataError, match="add up"):
            validate([cars[0] | {"car": "9.000"}, *cars[1:]], drivers)

    def test_check_sources(self) -> None:
        with pytest.raises(DataError, match="expected races"):
            check_sources(world_tables())

    def test_check_expected(self) -> None:
        cars, drivers = build(world_tables(), [], iterations=20)

        with pytest.raises(DataError, match="expected counts"):
            check_expected(cars, drivers)


def test_read_tables(tmp_path: Path) -> None:
    path = tmp_path / "f1db-csv.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for key, name in TABLE_FILES.items():
            archive.writestr(name, f"id,name\n{key},Name é\n")

    tables = read_tables(path)

    assert tables["races"] == [{"id": "races", "name": "Name é"}]
    assert set(tables) == set(TABLE_FILES)


def test_bundled_files_match_the_columns() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "eighty_two_o" / "sweep"
    for name, columns in (("cars.csv", CAR_COLUMNS), ("drivers.csv", DRIVER_COLUMNS)):
        header = next(csv.reader(io.StringIO((root / name).read_text(encoding="utf-8"))))
        assert tuple(header) == columns
