# 82-0 Game

Can you draft a team that goes a perfect 82-0? Or build a car that wins every race?
There are two games: **82-0** (basketball) and **Clean Sweep** (motor racing). Pick one on the
home page.

## 82-0

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

### 82-0 rules

- **Modes**: *Rookie* shows every player's stat line while you draft. *Legend* shows only names
  and positions, sorted alphabetically, and reveals the stats once the season starts.
- **Rerolls**: two for the whole draft. A reroll swaps the team on the board for another one.
- **One of each player**: once you draft someone, his other seasons are off the table.
- **Lineup**: any five starters, no position slots. The simulation judges the fit.
- **Seeds**: every game has a seed, shown at the end. The same seed and the same picks always
  play out the same season.

### How a basketball team is judged

Each player's value comes from his Box Plus/Minus that season, which is computed from his box
score and measured against the league average of his own era. The team rating then accounts for:

- **Shot sharing**: there is one ball. Five high-usage scorers do not simply add up.
- **Playmaking** and **rebounding**: a team with too little of either pays for it.
- **Position fit**: starters far from their natural position cost points.

Each game's margin is drawn around the gap between your rating and the opponent's real net
rating, plus home court. A team of all-time greats goes 82-0 about half the time, and the
1995-96 Bulls average about 73 wins. A good draft from random rolls goes 82-0 about once in
30 tries.

## Clean Sweep

Seven rounds. Each round rolls a real race-winning team from a season between 1980 and 2025
(164 of them), for example the 1992 Williams FW14B with its Renault engine. You take **one
thing** from it: its engine, its chassis (which stands for chassis and aerodynamics), its
reliability, its pit crew or one of its drivers. Fill four parts and three driver seats, so
your car can carry a 2014 Mercedes engine in a 1992 Williams chassis with a 2001 McLaren pit
crew. Then mark one driver as the reserve.

The season is 20 races, each against the full real field of a different season: every team of
that year with its two main drivers. Win all 20 with either of your cars for a clean sweep.

- **Modes**: *Rookie* shows a 1 to 99 rating and the real numbers behind every part and driver.
  *Legend* shows names only, drivers sorted alphabetically, and reveals the numbers once your
  team is set.
- **Rerolls**: two for the whole draft. A team-season is never rolled twice in one draft.
- **One of each driver**: once you take someone, his other seasons are off the table.
- **The reserve** drives when a main driver misses a race (about 3% of races for each).
- **Seeds**: the same seed and the same picks always race the same season.

### How a car is judged

The ratings come from finishing orders. A Plackett-Luce model, fitted to every race and
qualifying session from 1975 to 2025, splits each result into the strength of the car and the
strength of the driver, measured against the average of that season. Then:

- **Engine**: what the best cars using that engine that year achieved, adjusted by written
  reports where results alone mislead (for example, the 2010 and 2011 Red Bulls won through
  their chassis, not their Renault engine). Every correction and its source is in
  `tools/sweep_corrections.csv`, and editing it changes the ratings.
- **Chassis**: the rest of the car's strength.
- **Pit crew**: pit-stop times against the rest of the field (timing starts in 1994; earlier
  crews are rated average).
- **Reliability**: mechanical retirements against the average of the era.

In each race, cars can break down or crash out (more often with a fragile car or a
crash-prone driver), and the running cars finish in order of strength plus luck. The 1988
McLaren, which really won 15 of 16 races, wins about 14.5 of 20 here against fields from every
era. A good draft from random rolls wins all 20 about once in 35 tries.

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
- `uv run python tools/build_sweep_dataset.py` downloads the pinned F1DB release (once, into
  `.cache/`) and rebuilds the Clean Sweep dataset, applying `tools/sweep_corrections.csv`.
- `uv run python tools/calibrate_sweep.py` prints how real cars do as built and how often
  simulated drafters get a clean sweep.

## Project layout

```
src/eighty_two_o/
  data/        bundled dataset (players.csv, teams.csv), models and loader
  draft.py     rolls, picks and rerolls
  rating.py    team rating from box-score value and fit
  season.py    the 82-game simulation
  game.py      a whole game's state and the game store
  store.py     the generic game store used by both games
  sweep/       Clean Sweep: dataset (cars.csv, drivers.csv), draft, team, season, game
  web/         FastAPI routes for both games, Jinja templates, CSS and the reveal script
  cli.py       the `eighty-two-o` command
tools/         dataset builds, Clean Sweep corrections and calibration reports
tests/         pytest tests, mirroring the package layout
```

## Data

**82-0**: statistics from [Basketball-Reference](https://www.basketball-reference.com/), via
[Sumitro Datta's CC0 dataset](https://github.com/sumitrodatta/bball-reference-datasets). The
game uses player names and statistics only: no team logos or player photos.

**Clean Sweep**: race results from [F1DB](https://github.com/f1db/f1db), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), turned into ratings by this game
(the ratings and the corrections are this game's own work). The game uses team, car, engine
and driver names as facts only: no logos or photos. Unofficial: not associated with the
Formula 1 companies.
