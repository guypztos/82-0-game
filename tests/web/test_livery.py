from eighty_two_o.sweep.models import PART_SLOTS, Slot
from eighty_two_o.sweep.repository import SweepDataset
from eighty_two_o.web.livery import (
    ENGINE_COLOURS,
    NEUTRAL,
    TEAM_LIVERIES,
    engine_colour,
    livery,
    part_colour,
)
from tests.factories import make_car


def test_eras() -> None:
    assert livery(make_car(constructor_id="mclaren", year=1988)).primary == "#f2f4f7"
    assert livery(make_car(constructor_id="mclaren", year=1997)).primary == "#a7adb5"
    assert livery(make_car(constructor_id="mclaren", year=2024)).primary == "#ff8000"


def test_unknown_team_and_engine() -> None:
    car = make_car(constructor_id="nobody", engine_id="nothing")

    assert livery(car) == NEUTRAL
    assert engine_colour(car) == NEUTRAL.primary


def test_part_colour() -> None:
    car = make_car(constructor_id="williams", year=1992, engine_id="renault")

    assert part_colour(Slot.ENGINE, car) == ENGINE_COLOURS["renault"]
    for slot in PART_SLOTS[1:]:
        assert part_colour(slot, car) == livery(car).primary


def test_every_rollable_team_and_engine_has_a_colour(sweep_dataset: SweepDataset) -> None:
    for car in sweep_dataset.rollable:
        assert car.constructor_id in TEAM_LIVERIES
        assert car.engine_id in ENGINE_COLOURS
