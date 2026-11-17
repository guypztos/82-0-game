import runpy

import pytest

from eighty_two_o import __version__
from eighty_two_o.cli import main


def test_version_is_set() -> None:
    assert __version__


def test_main_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    main()

    assert __version__ in capsys.readouterr().out


def test_package_runs_as_a_module(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_module("eighty_two_o", run_name="__main__")

    assert __version__ in capsys.readouterr().out
