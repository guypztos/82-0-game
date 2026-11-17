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

Game logic is pure (no input/output) and the browser is a thin layer on top:

- `data/`: the bundled `players.csv` / `teams.csv` (built by `tools/build_dataset.py`, never
  edited by hand), the `PlayerSeason` / `TeamSeason` models and the `Dataset` index.
- `config.py`: every tunable number (`DraftConfig`, `RatingConfig`, `SimConfig`), including
  special cards (`RatingConfig.card_boosts`).
- `draft.py` → `rating.py` → `season.py`: the draft, the team rating and the 82-game sim.
- `game.py`: a whole game as an immutable `Game` (phases draft → lineup → done) and the
  `GameStore` protocol with its in-memory implementation.
- `web/`: FastAPI routes, Jinja templates and static CSS/JS. Server-rendered forms with
  post/redirect/get; Legend mode must never send stats to the browser before the lineup.
- `cli.py`: the `eighty-two-o` command (uvicorn plus opening the browser).
- `tools/`: `build_dataset.py` and `calibrate.py` (the calibration report).
- `tests/`: mirrors the package. `tests/factories.py` builds small fake records and datasets;
  the `dataset` fixture in `tests/conftest.py` is the real bundled data.

Conventions:

- All state is frozen pydantic models that round-trip through JSON.
- Randomness comes only from the game's seed (`random.Random(f"{seed}:...")`), so the same seed
  and choices replay the same game. Never store a generator in state.
- The rating and season tests pin values measured on the real data. If one fails, the change
  broke the model: re-run `tools/calibrate.py` and only re-pin numbers on purpose.
