import random

import pytest

from eighty_two_o.data.repository import Dataset
from tools.calibrate import main, season_odds


def test_season_odds_are_probabilities(dataset: Dataset) -> None:
    expected_wins, perfect = season_odds(10.0, dataset, random.Random(1))

    assert 0 < expected_wins < 82
    assert 0 <= perfect < 1


def test_report_runs_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--drafts", "10", "--schedules", "2"])

    out = capsys.readouterr().out
    assert "correlation with real net rating" in out
    assert "1995-96 Chicago Bulls" in out
    assert "chance of 82-0" in out
