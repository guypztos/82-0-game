import runpy
import webbrowser
from collections.abc import Callable
from typing import Any

import pytest
import uvicorn

from eighty_two_o import cli


class Recorder:
    """Stands in for uvicorn.run, webbrowser.open and threading.Timer."""

    def __init__(self) -> None:
        self.run_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.opened: list[str] = []
        self.delays: list[float] = []

    def run(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401 - mirrors uvicorn.run
        self.run_calls.append((args, kwargs))

    def open(self, url: str) -> bool:
        self.opened.append(url)
        return True

    def timer(
        self, interval: float, function: Callable[..., object], args: tuple[object, ...]
    ) -> "Recorder.FakeTimer":
        self.delays.append(interval)
        return Recorder.FakeTimer(function, args)

    class FakeTimer:
        def __init__(self, function: Callable[..., object], args: tuple[object, ...]) -> None:
            self.function = function
            self.args = args

        def start(self) -> None:
            self.function(*self.args)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(uvicorn, "run", recorder.run)
    monkeypatch.setattr(webbrowser, "open", recorder.open)
    monkeypatch.setattr(cli, "Timer", recorder.timer)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    return recorder


def test_defaults(recorder: Recorder, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main()

    assert recorder.run_calls == [
        (
            ("eighty_two_o.web.app:create_app",),
            {"factory": True, "host": "127.0.0.1", "port": 8000},
        )
    ]
    assert recorder.opened == ["http://127.0.0.1:8000/"]
    assert recorder.delays == [cli.BROWSER_DELAY_SECONDS]
    assert "http://127.0.0.1:8000/" in capsys.readouterr().out


def test_host_and_port_from_the_environment(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOST", "localhost")
    monkeypatch.setenv("PORT", "9001")

    cli.main()

    assert recorder.run_calls[0][1] == {"factory": True, "host": "localhost", "port": 9001}
    assert recorder.opened == ["http://localhost:9001/"]


def test_all_interfaces_opens_localhost(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOST", "0.0.0.0")

    cli.main()

    assert recorder.run_calls[0][1]["host"] == "0.0.0.0"
    assert recorder.opened == ["http://127.0.0.1:8000/"]


def test_package_runs_as_a_module(recorder: Recorder) -> None:
    runpy.run_module("eighty_two_o", run_name="__main__")

    assert len(recorder.run_calls) == 1
