# 82-0 Game

Can you draft a team that goes a perfect 82-0?

Eight rounds. Each round rolls a random real NBA team from any season since 1979-80, and you
draft one player from that roster: *that season's* version of him. Prime Steph Curry and
late-career Steph Curry are different cards. Pick five starters and three bench players, then
watch your team play 82 games against real teams from history, one result at a time.

## Play

You need [uv](https://docs.astral.sh/uv/) (`brew install uv`). It installs the right Python
version and every dependency for you.

```sh
make setup   # once per clone: install dependencies and git hooks
make run     # start the game and open it in your browser
```

The game runs at <http://127.0.0.1:8000/>. Set `HOST` and `PORT` to change that.

### Rules

- **Modes**: *Rookie* shows every player's stat line while you draft. *Legend* shows only names
  and positions, sorted alphabetically, and reveals the stats once the season starts.
- **Rerolls**: two for the whole draft. A reroll swaps the team on the board for another one.
- **One of each player**: once you draft someone, his other seasons are off the table.
- **Lineup**: any five starters, no position slots. The simulation judges the fit.
- **Seeds**: every game has a seed, shown at the end. The same seed and the same picks always
  play out the same season.

### How a team is judged

Each player's value comes from his Box Plus/Minus that season, which is computed from his box
score and measured against the league average of his own era. The team rating then accounts for:

- **Shot sharing**: there is one ball. Five high-usage scorers do not simply add up.
- **Playmaking** and **rebounding**: a team with too little of either pays for it.
- **Position fit**: starters far from their natural position cost points.

Each game's margin is drawn around the gap between your rating and the opponent's real net
rating, plus home court. A team of all-time greats goes 82-0 about half the time, and the
1995-96 Bulls average about 73 wins. A good draft from random rolls goes 82-0 about once in
30 tries.

## Development

| Command          | What it does                                      |
| ---------------- | ------------------------------------------------- |
| `make format`    | Format the code and apply safe lint fixes         |
| `make lint`      | Check formatting and lint rules                   |
| `make typecheck` | Run mypy in strict mode                           |
| `make test`      | Run the tests with coverage (90% minimum)         |
| `make check`     | Everything above, exactly what CI runs            |
| `make run`       | Play the game                                     |

Quality gates run automatically at three points:

1. **On commit**: formatting, lint, strict type checking and the test suite.
2. **On push**: the test suite again.
3. **On GitHub**: the full `make check` for every pull request and push to `main`.

Direct commits to `main` are blocked by a git hook. Work on a branch and merge it.

Developer tools:

- `uv run python tools/build_dataset.py` rebuilds the bundled dataset from the source CSVs.
- `uv run python tools/calibrate.py` prints how well the rating matches real teams and how
  often simulated drafters go 82-0.

## Project layout

```
src/eighty_two_o/
  data/        bundled dataset (players.csv, teams.csv), models and loader
  draft.py     rolls, picks and rerolls
  rating.py    team rating from box-score value and fit
  season.py    the 82-game simulation
  game.py      a whole game's state and the game store
  web/         FastAPI routes, Jinja templates, CSS and the reveal script
  cli.py       the `eighty-two-o` command
tools/         dataset build and calibration report
tests/         pytest tests, mirroring the package layout
```

## Data

Statistics from [Basketball-Reference](https://www.basketball-reference.com/), via
[Sumitro Datta's CC0 dataset](https://github.com/sumitrodatta/bball-reference-datasets). The
game uses player names and statistics only: no team logos or player photos.
