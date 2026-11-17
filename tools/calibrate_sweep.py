"""Print the calibration report for Clean Sweep.

Run with ``uv run python tools/calibrate_sweep.py``. It shows how real cars do when they race
as built, and how often simulated players get a clean sweep:

- *skilled*: compares each item on the board with what the remaining rolls can be expected to
  offer, takes the best one, and rerolls when nothing beats that expectation;
- *random*: takes a random legal item and never rerolls.

Both draft through the real draft engine and play real simulated seasons.
"""

import argparse
import random
import statistics
from collections.abc import Callable, Sequence

from eighty_two_o.config import DEFAULT_SWEEP_SIM
from eighty_two_o.sweep.draft import (
    ROUNDS,
    TEAM_DRIVERS,
    SweepDraft,
    board,
    pick,
    reroll,
    rerolls_left,
    start_draft,
)
from eighty_two_o.sweep.models import PART_SLOTS, CarSeason, DriverSeason, Slot
from eighty_two_o.sweep.repository import SweepDataset, load_sweep_dataset
from eighty_two_o.sweep.season import simulate_season
from eighty_two_o.sweep.team import Team

RELIABILITY_WEIGHT = -2.5
DRIVER_WEIGHT = 0.8
RESERVE_WEIGHT = 0.1

type Policy = Callable[[SweepDraft, SweepDataset, random.Random], str | None]
"""Returns the item to take, or ``None`` to reroll."""

AS_BUILT = (
    ("mclaren:1988", "gerhard-berger:1988:ferrari"),
    ("mercedes:2014", "valtteri-bottas:2014:williams"),
    ("red-bull:2023", "daniel-ricciardo:2023:alphatauri"),
    ("brawn:2009", "sebastian-vettel:2009:red-bull"),
    ("jordan:1999", "jarno-trulli:1999:prost"),
)


def part_score(slot: Slot, car: CarSeason) -> float:
    """How much the skilled policy values a part.

    Args:
        slot: One of ``PART_SLOTS``.
        car: The car the part comes from.

    Returns:
        Its strength, or ``-2.5`` times its reliability ratio.
    """
    if slot is Slot.ENGINE:
        return car.engine
    if slot is Slot.CHASSIS:
        return car.chassis
    if slot is Slot.PIT_CREW:
        return car.pit
    return RELIABILITY_WEIGHT * car.reliability


def expected_best(values: Sequence[float], draws: int) -> float:
    """The expected maximum of ``draws`` random picks (with replacement) from ``values``.

    Args:
        values: The values, in any order.
        draws: How many picks.

    Returns:
        The expected best.
    """
    ordered = sorted(values)
    n = len(ordered)
    return sum(v * (((i + 1) / n) ** draws - (i / n) ** draws) for i, v in enumerate(ordered))


class Skilled:
    """The reference skilled drafter."""

    def __init__(self, dataset: SweepDataset) -> None:
        """Measure what the rolls offer.

        Args:
            dataset: The dataset the draft rolls from.
        """
        self._values: dict[Slot, list[float]] = {
            slot: [part_score(slot, car) for car in dataset.rollable] for slot in PART_SLOTS
        }
        self._values[Slot.DRIVER] = [
            max(d.career for d in dataset.roster(car.key)) for car in dataset.rollable
        ]
        self._cache: dict[tuple[Slot, int], float] = {}

    def _best(self, slot: Slot, draws: int) -> float:
        key = (slot, draws)
        if key not in self._cache:
            self._cache[key] = expected_best(self._values[slot], draws)
        return self._cache[key]

    def __call__(self, state: SweepDraft, dataset: SweepDataset, rng: random.Random) -> str | None:
        """Choose an item or a reroll.

        Args:
            state: The draft.
            dataset: The dataset.
            rng: Unused; the policy is deterministic.

        Returns:
            The item, or ``None`` to reroll.
        """
        del rng
        left = ROUNDS - state.picks_made - 1
        spare = rerolls_left(state)
        draws = max(1, round((left + spare) / left)) if left > 0 else 1
        b = board(state, dataset)
        options: list[tuple[float, str]] = [
            (part_score(o.slot, b.car) - self._best(o.slot, draws), o.slot.value)
            for o in b.parts
            if o.available
        ]
        for option in b.drivers:
            if option.available:
                options.append(
                    (self._driver_advantage(state, option.card, draws), _item(option.card))
                )
        advantage, item = max(options)
        if advantage < 0 and spare > 0:
            return None
        return item

    def _driver_advantage(self, state: SweepDraft, card: DriverSeason, draws: int) -> float:
        if len(state.drivers) < TEAM_DRIVERS - 1:
            return DRIVER_WEIGHT * (card.career - self._best(Slot.DRIVER, draws))
        low = min(d.career for d in state.drivers)
        return DRIVER_WEIGHT * max(0.0, card.career - low) + RESERVE_WEIGHT * (
            min(card.career, low) - self._best(Slot.DRIVER, 1)
        )


def _item(card: DriverSeason) -> str:
    return f"driver:{card.card_id}"


def random_policy(state: SweepDraft, dataset: SweepDataset, rng: random.Random) -> str | None:
    """Take a random legal item; never reroll.

    Args:
        state: The draft.
        dataset: The dataset.
        rng: Where the choice comes from.

    Returns:
        The item.
    """
    b = board(state, dataset)
    items = [o.slot.value for o in b.parts if o.available]
    items += [_item(o.card) for o in b.drivers if o.available]
    return rng.choice(items)


def draft_team(dataset: SweepDataset, seed: int, policy: Policy) -> Team:
    """Draft a whole team with a policy; the two best-rated drivers race.

    Args:
        dataset: The dataset.
        seed: The draft's seed.
        policy: How items are chosen.

    Returns:
        The team.
    """
    rng = random.Random(f"policy:{seed}")
    state = start_draft(dataset, seed)
    while not state.complete:
        item = policy(state, dataset, rng)
        state = reroll(state, dataset) if item is None else pick(state, dataset, item)
    first, second, reserve = sorted(state.drivers, key=lambda d: -d.career)
    parts = {slot.value: state.part(slot) for slot in PART_SLOTS}
    return Team.model_validate({**parts, "mains": (first, second), "reserve": reserve})


def season_report(team: Team, dataset: SweepDataset, seeds: Sequence[int]) -> tuple[float, float]:
    """Average wins and clean-sweep share of a team over many seasons.

    Args:
        team: The team.
        dataset: The dataset.
        seeds: Season seeds.

    Returns:
        ``(average wins, share of clean sweeps)``.
    """
    seasons = [simulate_season(team, dataset, seed) for seed in seeds]
    return statistics.fmean(s.wins for s in seasons), sum(s.perfect for s in seasons) / len(seeds)


def policy_report(
    dataset: SweepDataset, name: str, policy: Policy, drafts: int, seasons: int
) -> list[str]:
    """Report how a drafting policy does.

    Args:
        dataset: The dataset.
        name: The policy's name.
        policy: The policy.
        drafts: How many drafts.
        seasons: Seasons per draft.

    Returns:
        Report lines.
    """
    wins: list[int] = []
    for draft_seed in range(drafts):
        team = draft_team(dataset, draft_seed, policy)
        wins += [simulate_season(team, dataset, draft_seed * 1000 + s).wins for s in range(seasons)]
    ordered = sorted(wins)
    sweeps = sum(w == DEFAULT_SWEEP_SIM.races for w in wins)
    return [
        f"{name} drafter: {drafts} drafts x {seasons} seasons",
        f"  average wins {statistics.fmean(wins):.2f} of {DEFAULT_SWEEP_SIM.races}"
        f" (10th, 50th, 90th percentile: {ordered[len(ordered) // 10]},"
        f" {ordered[len(ordered) // 2]}, {ordered[9 * len(ordered) // 10]})",
        f"  clean sweeps {100 * sweeps / len(wins):.2f}% ({sweeps} of {len(wins)})",
    ]


def main(argv: Sequence[str] | None = None) -> None:
    """Print the report.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.
    """
    parser = argparse.ArgumentParser(description="Clean Sweep calibration report.")
    parser.add_argument("--drafts", type=int, default=600)
    parser.add_argument("--seasons", type=int, default=30)
    parser.add_argument("--as-built-seasons", type=int, default=2000)
    args = parser.parse_args(argv)
    dataset = load_sweep_dataset()

    lines = ["Real cars as built (both main drivers, reserve from elsewhere)"]
    for key, reserve in AS_BUILT:
        car = dataset.car(key)
        team = Team(
            engine=car,
            chassis=car,
            reliability=car,
            pit_crew=car,
            mains=dataset.mains(key),
            reserve=dataset.driver(reserve),
        )
        wins, sweeps = season_report(team, dataset, range(args.as_built_seasons))
        lines.append(
            f"  {car.full_label:<45} car {car.car:+.2f}  average wins {wins:5.2f}"
            f"  clean sweeps {100 * sweeps:.2f}%"
        )
    lines += policy_report(dataset, "Skilled", Skilled(dataset), args.drafts, args.seasons)
    lines += policy_report(dataset, "Random", random_policy, args.drafts, args.seasons)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
