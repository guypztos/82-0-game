import pytest

from eighty_two_o.config import SweepSimConfig
from eighty_two_o.sweep.models import PART_SLOTS, Slot
from eighty_two_o.sweep.repository import SweepDataset
from eighty_two_o.sweep.team import (
    Team,
    car_strength,
    display_rating,
    part_value,
    retirement_chances,
)
from tests.factories import make_car, make_driver


def make_team() -> Team:
    return Team(
        engine=make_car(constructor_id="e", engine=1.5, chassis=-9.0, pit=-9.0),
        chassis=make_car(constructor_id="c", engine=-9.0, chassis=2.0, pit=-9.0),
        reliability=make_car(constructor_id="r", reliability=0.5),
        pit_crew=make_car(constructor_id="p", engine=-9.0, chassis=-9.0, pit=0.25),
        mains=(make_driver(driver_id="a"), make_driver(driver_id="b")),
        reserve=make_driver(driver_id="c"),
    )


def test_car_strength_takes_each_part_from_its_own_car() -> None:
    assert car_strength(make_team()) == pytest.approx(3.75)


def test_parts_and_drivers() -> None:
    team = make_team()

    assert [team.part(slot).constructor_id for slot in PART_SLOTS] == ["e", "c", "r", "p"]
    assert [d.driver_id for d in team.drivers] == ["a", "b", "c"]
    assert [part_value(slot, team.part(slot)) for slot in PART_SLOTS] == [1.5, 2.0, 0.5, 0.25]
    with pytest.raises(ValueError, match="not a part"):
        part_value(Slot.DRIVER, team.engine)


def test_retirement_chances() -> None:
    config = SweepSimConfig(mechanical_rate=0.1, incident_rate=0.05, retirement_cap=0.6)

    assert retirement_chances(1.0, 1.0, config) == pytest.approx((0.1, 0.05))
    assert retirement_chances(2.0, 4.0, config) == pytest.approx((0.2, 0.2))
    mechanical, incident = retirement_chances(6.0, 4.0, config)  # 0.6 + 0.2, over the cap
    assert mechanical + incident == pytest.approx(0.6)
    assert mechanical / incident == pytest.approx(3.0)


def test_display_rating_is_clamped() -> None:
    assert display_rating(Slot.ENGINE, 0.0) == 60
    assert display_rating(Slot.ENGINE, 10.0) == 99
    assert display_rating(Slot.CHASSIS, -10.0) == 1
    assert display_rating(Slot.RELIABILITY, 1.0) == 60
    assert display_rating(Slot.RELIABILITY, 0.5) > display_rating(Slot.RELIABILITY, 1.5)


@pytest.mark.parametrize(
    ("slot", "key", "expected"),
    [
        (Slot.ENGINE, "mercedes:2014", 98),
        (Slot.CHASSIS, "williams:1992", 99),
        (Slot.CHASSIS, "red-bull:2023", 75),
        (Slot.PIT_CREW, "mclaren:2001", 99),
        (Slot.RELIABILITY, "benetton:1995", 98),
    ],
)
def test_pinned_part_ratings(
    sweep_dataset: SweepDataset, slot: Slot, key: str, expected: int
) -> None:
    assert display_rating(slot, part_value(slot, sweep_dataset.car(key))) == expected


@pytest.mark.parametrize(
    ("card_id", "expected"),
    [("max-verstappen:2025:red-bull", 98), ("sergio-perez:2023:red-bull", 52)],
)
def test_pinned_driver_ratings(sweep_dataset: SweepDataset, card_id: str, expected: int) -> None:
    assert display_rating(Slot.DRIVER, sweep_dataset.driver(card_id).rating) == expected
