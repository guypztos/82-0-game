from eighty_two_o.sweep.models import PART_SLOTS, Slot
from tests.factories import make_car, make_driver


def test_car_labels() -> None:
    car = make_car(constructor_id="williams", year=1992, name="Williams", chassis_name="FW14B")
    car = car.model_copy(update={"engine_name": "Renault"})

    assert car.key == "williams:1992"
    assert car.label == "1992 Williams"
    assert car.full_label == "1992 Williams FW14B, Renault engine"


def test_driver_ids() -> None:
    driver = make_driver(driver_id="max-verstappen", name="Max", year=2025, constructor_id="rb")

    assert driver.card_id == "max-verstappen:2025:rb"
    assert driver.car_key == "rb:2025"
    assert driver.label == "Max (2025)"


def test_slots() -> None:
    assert [slot.value for slot in PART_SLOTS] == ["engine", "chassis", "reliability", "pit_crew"]
    assert Slot.PIT_CREW.label == "Pit crew"
    assert Slot.DRIVER not in PART_SLOTS


def test_round_trip() -> None:
    car = make_car(pit_rank=None, championship_position=None)

    assert type(car).model_validate_json(car.model_dump_json()) == car
