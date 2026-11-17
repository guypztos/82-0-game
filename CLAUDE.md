# 82-0 Game

A draft-and-simulate basketball game: the player drafts an NBA team (five starters and three
bench players), then the game simulates an 82-game season to see whether the team goes 82-0.
A hobby project that may be shared with others, so it must be easy to install and run.

## Commands

- `make check`: format check, lint, mypy, tests. Run it before saying work is done.
- `make format`: format and autofix.
- `make test`: tests with coverage. `uv run pytest tests/test_x.py::test_name` for one test.
- `make run`: run the game.
- `uv add <pkg>` / `uv add --dev <pkg>`: add dependencies. Never edit `uv.lock` by hand.

## Rules

- Every stage of work ships with its tests in the same commit. Coverage must stay at 90% or
  above; do not lower the threshold or add `# pragma: no cover` to get past it.
- Every function, method and test is fully type annotated. mypy runs in strict mode; fix the
  types instead of adding `# type: ignore` or `Any`.
- Public modules, classes and functions get a Google-style docstring.
- Never commit to `main` directly (a hook blocks it). Create a branch per stage of work.
- Do not skip hooks with `--no-verify`.

## Structure

- `src/eighty_two_o/`: the package. Keep game logic (draft, simulation, data) free of any
  input/output so it can be tested without a terminal; the user interface is a thin layer on
  top. `cli.py` holds the command-line entry point.
- `tests/`: mirrors the package, one `test_<module>.py` per module.
- Randomness must be injectable (pass a `random.Random` or a seed) so simulations are
  reproducible in tests.
