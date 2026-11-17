# 82-0 Game

A fun interactive 82-0 challenge: draft a basketball team (NBA only for now), a starting
lineup of five plus three bench players, then simulate a full season and see whether your
team can go a perfect 82-0.

The game is in early development and is not playable yet.

## Getting started

You need [uv](https://docs.astral.sh/uv/) (`brew install uv`). It installs the right Python
version and every dependency for you.

```sh
make setup   # install dependencies and git hooks (once per clone)
make run     # play the game
```

## Development

| Command          | What it does                                      |
| ---------------- | ------------------------------------------------- |
| `make format`    | Format the code and apply safe lint fixes         |
| `make lint`      | Check formatting and lint rules                   |
| `make typecheck` | Run mypy in strict mode                           |
| `make test`      | Run the tests with coverage (90% minimum)         |
| `make check`     | Everything above, exactly what CI runs            |

Quality gates run automatically at three points:

1. **On commit**: formatting, lint, strict type checking and the test suite.
2. **On push**: the test suite again.
3. **On GitHub**: the full `make check` for every pull request and push to `main`.

Direct commits to `main` are blocked by a git hook. Work on a branch and merge it:

```sh
git switch -c my-feature
```

## Project layout

```
src/eighty_two_o/   the game package
tests/              pytest tests, mirroring the package layout
```
