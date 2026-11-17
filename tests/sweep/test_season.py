import statistics

import pytest

from eighty_two_o.config import SweepSimConfig
from eighty_two_o.sweep.repository import SweepDataset
from eighty_two_o.sweep.season import CarResult, RaceResult, SweepSeason, simulate_season
from eighty_two_o.sweep.team import Team

SEEDS = range(2000)


def as_built(dataset: SweepDataset, key: str, reserve: str) -> Team:
    car = dataset.car(key)
    return Team(
        engine=car,
        chassis=car,
        reliability=car,
        pit_crew=car,
        mains=dataset.mains(key),
        reserve=dataset.driver(reserve),
    )


def mixed(
    dataset: SweepDataset, engine: str, chassis: str, rel: str, pit: str, *drivers: str
) -> Team:
    first, second, reserve = (dataset.driver(card) for card in drivers)
    return Team(
        engine=dataset.car(engine),
        chassis=dataset.car(chassis),
        reliability=dataset.car(rel),
        pit_crew=dataset.car(pit),
        mains=(first, second),
        reserve=reserve,
    )


def all_time(dataset: SweepDataset) -> Team:
    return mixed(
        dataset,
        "mercedes:2014",
        "williams:1992",
        "benetton:1995",
        "mclaren:2001",
        "max-verstappen:2025:red-bull",
        "michael-schumacher:1994:benetton",
        "ayrton-senna:1989:mclaren",
    )


def odds(team: Team, dataset: SweepDataset) -> tuple[float, float]:
    seasons = [simulate_season(team, dataset, seed) for seed in SEEDS]
    return statistics.fmean(s.wins for s in seasons), sum(s.perfect for s in seasons) / len(SEEDS)


class TestPinned:
    def test_all_time_team(self, sweep_dataset: SweepDataset) -> None:
        wins, sweeps = odds(all_time(sweep_dataset), sweep_dataset)

        assert wins >= 19.8
        assert 0.87 <= sweeps <= 0.93

    def test_mclaren_1988(self, sweep_dataset: SweepDataset) -> None:
        team = as_built(sweep_dataset, "mclaren:1988", "gerhard-berger:1988:ferrari")
        wins, sweeps = odds(team, sweep_dataset)

        assert 14.0 <= wins <= 15.1
        assert sweeps < 0.01

    def test_red_bull_2023(self, sweep_dataset: SweepDataset) -> None:
        team = as_built(sweep_dataset, "red-bull:2023", "daniel-ricciardo:2023:alphatauri")
        wins, sweeps = odds(team, sweep_dataset)

        assert 8.0 <= wins <= 9.0
        assert sweeps == 0

    def test_mixed_team(self, sweep_dataset: SweepDataset) -> None:
        team = mixed(
            sweep_dataset,
            "ferrari:2019",
            "brawn:2009",
            "mclaren:1988",
            "red-bull:2013",
            "lewis-hamilton:2018:mercedes",
            "fernando-alonso:2012:ferrari",
            "jenson-button:2009:brawn",
        )
        wins, sweeps = odds(team, sweep_dataset)

        assert 6.8 <= wins <= 7.9
        assert sweeps == 0

    def test_jordan_1999(self, sweep_dataset: SweepDataset) -> None:
        team = as_built(sweep_dataset, "jordan:1999", "jarno-trulli:1999:prost")
        wins, sweeps = odds(team, sweep_dataset)

        assert 0.7 <= wins <= 1.3
        assert sweeps == 0


class TestRules:
    def test_twenty_different_fields(self, sweep_dataset: SweepDataset) -> None:
        season = simulate_season(all_time(sweep_dataset), sweep_dataset, 1)

        assert [race.number for race in season.races] == list(range(1, 21))
        assert len({race.year for race in season.races}) == 20

    def test_deterministic(self, sweep_dataset: SweepDataset) -> None:
        team = all_time(sweep_dataset)

        assert simulate_season(team, sweep_dataset, 5) == simulate_season(team, sweep_dataset, 5)
        assert simulate_season(team, sweep_dataset, 5) != simulate_season(team, sweep_dataset, 6)

    def test_positions_and_retirements(self, sweep_dataset: SweepDataset) -> None:
        team = as_built(sweep_dataset, "red-bull:2023", "daniel-ricciardo:2023:alphatauri")
        seen_retirement = False
        for seed in range(40):
            for race in simulate_season(team, sweep_dataset, seed).races:
                for car in race.cars:
                    assert (car.position is None) == (car.retirement is not None)
                    if car.position is not None:
                        assert 1 <= car.position <= race.finishers
                    seen_retirement |= car.retirement is not None
                assert race.won == any(car.position == 1 for car in race.cars)
                assert (race.winner_car is None) == (race.won or race.winner is None)
        assert seen_retirement

    def test_reserve(self, sweep_dataset: SweepDataset) -> None:
        team = all_time(sweep_dataset)
        never = simulate_season(team, sweep_dataset, 2, SweepSimConfig(absence_rate=0.0))
        always = simulate_season(team, sweep_dataset, 2, SweepSimConfig(absence_rate=0.5))

        assert not any(car.reserve for race in never.races for car in race.cars)
        for race in always.races:
            reserves = [car for car in race.cars if car.reserve]
            assert [car.driver for car in reserves] == ["Ayrton Senna"]

    def test_no_retirements_without_rates(self, sweep_dataset: SweepDataset) -> None:
        config = SweepSimConfig(mechanical_rate=0.0, incident_rate=0.0, absence_rate=0.0)
        team = all_time(sweep_dataset)

        for seed in range(10):
            season = simulate_season(team, sweep_dataset, seed, config)
            assert season.retirements == 0
            assert all(
                race.finishers == len(sweep_dataset.grid(race.year)) * 2 + 2
                for race in season.races
            )

    def test_everyone_breaking_down(self, sweep_dataset: SweepDataset) -> None:
        config = SweepSimConfig(mechanical_rate=100.0, retirement_cap=0.99)
        season = simulate_season(all_time(sweep_dataset), sweep_dataset, 3, config)

        assert season.wins <= 3
        assert any(race.winner is None for race in season.races)


def car(position: int | None, driver: str = "A") -> CarResult:
    return CarResult(
        driver=driver,
        reserve=False,
        position=position,
        retirement=None if position is not None else "mechanical",
    )


def race(number: int, *positions: int | None) -> RaceResult:
    first, second = positions
    won = 1 in positions
    return RaceResult(
        number=number,
        year=2000,
        won=won,
        winner="A" if won else "Rival",
        winner_car=None if won else "2000 Rival",
        cars=(car(first), car(second, "B")),
        finishers=20,
    )


def test_season_properties() -> None:
    season = SweepSeason(
        races=(
            race(1, 1, 2),
            race(2, 3, None),
            race(3, 1, 5),
            race(4, 2, 1),
            race(5, 1, None),
            race(6, None, None),
        )
    )

    assert (season.wins, season.losses, season.record) == (4, 2, "4 of 6")
    assert not season.perfect
    assert season.first_loss is not None
    assert season.first_loss.number == 2
    assert season.longest_win_streak == 3
    assert season.one_twos == 2
    assert season.retirements == 4
    assert [r.number for r in season.beaten_by] == [2, 6]


def test_perfect_season() -> None:
    season = SweepSeason(races=(race(1, 1, 2), race(2, 4, 1)))

    assert season.perfect
    assert season.first_loss is None
    assert season.beaten_by == ()


@pytest.mark.parametrize("seed", [0, 1])
def test_round_trip(sweep_dataset: SweepDataset, seed: int) -> None:
    season = simulate_season(all_time(sweep_dataset), sweep_dataset, seed)

    assert SweepSeason.model_validate_json(season.model_dump_json()) == season
