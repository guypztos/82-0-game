import pytest

from eighty_two_o.sweep.models import Slot
from eighty_two_o.sweep.repository import SweepDataset
from tests.factories import make_car
from tools.calibrate_sweep import (
    Skilled,
    draft_team,
    expected_best,
    main,
    part_score,
    random_policy,
    season_report,
)


def test_expected_best() -> None:
    assert expected_best([1.0, 2.0, 3.0], 1) == pytest.approx(2.0)
    assert expected_best([0.0, 1.0], 2) == pytest.approx(0.75)
    assert expected_best([5.0, 1.0, 3.0], 50) == pytest.approx(5.0)


def test_part_score() -> None:
    car = make_car(engine=1.0, chassis=2.0, pit=0.5, reliability=0.4)

    assert [part_score(slot, car) for slot in Slot if slot is not Slot.DRIVER] == [
        1.0,
        2.0,
        -1.0,
        0.5,
    ]


def test_skilled_beats_random(sweep_dataset: SweepDataset) -> None:
    skilled = Skilled(sweep_dataset)
    good = [
        season_report(draft_team(sweep_dataset, s, skilled), sweep_dataset, range(20))[0]
        for s in range(8)
    ]
    bad = [
        season_report(draft_team(sweep_dataset, s, random_policy), sweep_dataset, range(20))[0]
        for s in range(8)
    ]

    assert sum(good) > sum(bad)


def test_teams_race_their_best_drivers(sweep_dataset: SweepDataset) -> None:
    team = draft_team(sweep_dataset, 3, random_policy)

    assert min(d.rating for d in team.mains) >= team.reserve.rating


def test_random_policy_takes_legal_items(sweep_dataset: SweepDataset) -> None:
    team = draft_team(sweep_dataset, 11, random_policy)

    assert len({d.driver_id for d in team.drivers}) == 3


def test_report_runs_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--drafts", "3", "--seasons", "2", "--as-built-seasons", "5"])

    out = capsys.readouterr().out
    assert "1988 McLaren MP4/4, Honda engine" in out
    assert "Skilled drafter: 3 drafts x 2 seasons" in out
    assert "Random drafter" in out
    assert "clean sweeps" in out
