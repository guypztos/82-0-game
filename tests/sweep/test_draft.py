import random

import pytest

from eighty_two_o.sweep.draft import (
    ROUNDS,
    SweepDraft,
    SweepDraftError,
    board,
    pick,
    reroll,
    rerolls_left,
    start_draft,
)
from eighty_two_o.sweep.models import PART_SLOTS, Slot
from eighty_two_o.sweep.repository import SweepDataset
from tests.factories import make_car, make_driver, make_sweep_dataset


@pytest.fixture
def small() -> SweepDataset:
    return make_sweep_dataset(years=(2000, 2001, 2002), cars_per_year=4, drivers_per_car=3)


def driver_item(state: SweepDraft, dataset: SweepDataset, index: int = 0) -> str:
    assert state.current_roll is not None
    return f"driver:{dataset.roster(state.current_roll)[index].card_id}"


def legal_items(state: SweepDraft, dataset: SweepDataset) -> list[str]:
    b = board(state, dataset)
    items = [option.slot.value for option in b.parts if option.available]
    return items + [f"driver:{o.card.card_id}" for o in b.drivers if o.available]


def random_draft(dataset: SweepDataset, seed: int) -> SweepDraft:
    rng = random.Random(seed)
    state = start_draft(dataset, seed)
    while not state.complete:
        state = pick(state, dataset, rng.choice(legal_items(state, dataset)))
    return state


class TestRolls:
    def test_same_seed_same_rolls(self, small: SweepDataset) -> None:
        assert start_draft(small, 7) == start_draft(small, 7)
        rolls = {start_draft(small, seed).current_roll for seed in range(30)}
        assert len(rolls) > 1

    def test_rolls_are_rollable_cars(self, sweep_dataset: SweepDataset) -> None:
        for seed in range(50):
            state = random_draft(sweep_dataset, seed)
            assert all(sweep_dataset.car(key).rollable for key in state.rolled)

    def test_reroll_changes_the_roll_and_never_repeats(self, small: SweepDataset) -> None:
        state = start_draft(small, 3)
        first = state.current_roll

        state = reroll(state, small)
        state = reroll(state, small)

        assert state.current_roll != first
        assert len(set(state.rolled)) == 3
        assert rerolls_left(state) == 0
        with pytest.raises(SweepDraftError, match="no rerolls"):
            reroll(state, small)

    def test_rolls_only_offer_legal_items(self) -> None:
        cars = [
            make_car(constructor_id="old", year=2000),
            make_car(constructor_id="old", year=2001),
        ]
        cars.append(make_car(constructor_id="new", year=2000))
        drivers = [
            make_driver(driver_id=f"p{j}", year=car.year, constructor_id="old")
            for car in cars[:2]
            for j in range(2)
        ]
        drivers += [make_driver(driver_id=f"q{j}", constructor_id="new") for j in range(2)]
        dataset = SweepDataset(cars, drivers)
        part = dataset.car("old:2000")
        taken = (dataset.driver("p0:2000:old"), dataset.driver("p1:2000:old"))

        for seed in range(30):
            state = SweepDraft(
                seed=seed, engine=part, chassis=part, reliability=part, pit_crew=part, drivers=taken
            )
            assert reroll(state, dataset).current_roll == "new:2000"

    def test_running_out_of_rolls(self) -> None:
        dataset = make_sweep_dataset(years=(2000,), cars_per_year=1)
        state = start_draft(dataset, 1)

        with pytest.raises(SweepDraftError, match="no team-seasons left"):
            reroll(state, dataset)


class TestPicks:
    def test_parts_fill_their_slots(self, small: SweepDataset) -> None:
        state = start_draft(small, 1)
        rolls = []
        for slot in PART_SLOTS:
            rolls.append(state.current_roll)
            state = pick(state, small, slot.value)

        for slot, key in zip(PART_SLOTS, rolls, strict=True):
            held = state.part(slot)
            assert held is not None
            assert held.key == key
        assert state.open_parts == ()
        assert state.picks_made == 4

    def test_a_full_draft(self, small: SweepDataset) -> None:
        state = start_draft(small, 2)
        for slot in PART_SLOTS:
            state = pick(state, small, slot.value)
        for _ in range(3):
            state = pick(state, small, driver_item(state, small))

        assert state.complete
        assert state.picks_made == ROUNDS
        assert state.current_roll is None
        assert len(state.rolled) == ROUNDS
        for action in (
            lambda: pick(state, small, "engine"),
            lambda: reroll(state, small),
            lambda: board(state, small),
        ):
            with pytest.raises(SweepDraftError, match="already over"):
                action()

    def test_errors(self, small: SweepDataset) -> None:
        state = pick(start_draft(small, 4), small, "engine")

        with pytest.raises(SweepDraftError, match="engine slot is already filled"):
            pick(state, small, "engine")
        with pytest.raises(SweepDraftError, match="not something"):
            pick(state, small, "wings")
        with pytest.raises(SweepDraftError, match="did not drive"):
            pick(state, small, "driver:nobody:2000:c0")

    def test_seats_full(self, small: SweepDataset) -> None:
        state = start_draft(small, 5)
        for _ in range(3):
            state = pick(state, small, driver_item(state, small))

        assert state.seats_full
        assert not any(option.available for option in board(state, small).drivers)
        with pytest.raises(SweepDraftError, match="seats are taken"):
            pick(state, small, driver_item(state, small))

    def test_a_person_only_once(self, sweep_dataset: SweepDataset) -> None:
        schumacher_94 = sweep_dataset.driver("michael-schumacher:1994:benetton")
        state = SweepDraft(seed=1, drivers=(schumacher_94,), current_roll="benetton:1995")

        with pytest.raises(SweepDraftError, match="Michael Schumacher is already in your team"):
            pick(state, sweep_dataset, "driver:michael-schumacher:1995:benetton")
        options = {o.card.driver_id: o.available for o in board(state, sweep_dataset).drivers}
        assert options["michael-schumacher"] is False
        assert options["johnny-herbert"] is True

    def test_board(self, small: SweepDataset) -> None:
        state = pick(start_draft(small, 6), small, "chassis")
        b = board(state, small)

        assert b.car.key == state.current_roll
        assert [o.slot for o in b.parts] == list(PART_SLOTS)
        chassis = next(o for o in b.parts if o.slot is Slot.CHASSIS)
        assert not chassis.available
        assert chassis.held is not None
        assert chassis.held.key == state.rolled[0]
        assert [o.card.card_id for o in b.drivers] == [d.card_id for d in small.roster(b.car.key)]

    def test_random_drafts_never_get_stuck(self, sweep_dataset: SweepDataset) -> None:
        for seed in range(200):
            state = random_draft(sweep_dataset, seed)
            assert state.complete
            assert len({d.driver_id for d in state.drivers}) == 3

    def test_round_trip(self, small: SweepDataset) -> None:
        state = pick(start_draft(small, 8), small, "engine")

        assert SweepDraft.model_validate_json(state.model_dump_json()) == state
