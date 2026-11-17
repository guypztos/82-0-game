"""Build the bundled NBA dataset from Sumitro Datta's Basketball-Reference CSVs.

Run it once with ``uv run python tools/build_dataset.py`` and commit the two CSV files it writes
to ``src/eighty_two_o/data/``. The source files are downloaded from a pinned commit of
``github.com/sumitrodatta/bball-reference-datasets`` and cached in ``.cache/``.

All the filtering rules live in :func:`build`, a pure function that is unit tested with small
fixture rows; :func:`main` only downloads, reads and writes files.
"""

import argparse
import csv
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

COMMIT = "3981e43c07e963db539c527beb8a7b4b99ec8716"
BASE_URL = f"https://raw.githubusercontent.com/sumitrodatta/bball-reference-datasets/{COMMIT}/Data/"
TOTALS_FILE = "Player Totals.csv"
ADVANCED_FILE = "Advanced.csv"
TEAMS_FILE = "Team Summaries.csv"

LEAGUE = "NBA"
FIRST_SEASON = 1980
DEFAULT_LAST_SEASON = 2026
MIN_MINUTES = 400.0
MIN_ROSTER = 8
POSITIONS = frozenset({"PG", "SG", "SF", "PF", "C"})
MISSING = frozenset({"", "NA"})

# Expected output for the pinned commit and the default last season.
EXPECTED_TEAM_SEASONS = 1314
EXPECTED_PLAYER_ROWS = 15928

PLAYER_COLUMNS = (
    "player_id",
    "name",
    "season",
    "team",
    "position",
    "age",
    "games",
    "minutes_total",
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "true_shooting",
    "usage",
    "assist_pct",
    "rebound_pct",
    "obpm",
    "dbpm",
)
TEAM_COLUMNS = ("team", "season", "name", "wins", "losses", "net_rating")

# Per-game output column -> source total column.
PER_GAME_COLUMNS = {
    "points": "pts",
    "rebounds": "trb",
    "assists": "ast",
    "steals": "stl",
    "blocks": "blk",
    "turnovers": "tov",
}
# Output column -> Advanced.csv column, copied unchanged.
ADVANCED_COLUMNS = {
    "true_shooting": "ts_percent",
    "usage": "usg_percent",
    "assist_pct": "ast_percent",
    "rebound_pct": "trb_percent",
    "obpm": "obpm",
    "dbpm": "dbpm",
}

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / COMMIT
OUTPUT_DIR = ROOT / "src" / "eighty_two_o" / "data"

type SourceRow = Mapping[str, str]
type OutputRow = dict[str, str]


class DataError(ValueError):
    """The source data breaks one of the assumptions the build relies on."""


def build(
    totals: Iterable[SourceRow],
    advanced: Iterable[SourceRow],
    teams: Iterable[SourceRow],
    last_season: int = DEFAULT_LAST_SEASON,
) -> tuple[list[OutputRow], list[OutputRow]]:
    """Turn the three source tables into the bundled player and team rows.

    Args:
        totals: Rows of ``Player Totals.csv``.
        advanced: Rows of ``Advanced.csv``.
        teams: Rows of ``Team Summaries.csv``.
        last_season: The last completed season to include (end year, e.g. 2026).

    Returns:
        The player rows and the team rows, each sorted and holding only output columns.

    Raises:
        DataError: If a kept row is missing a needed value, has an unknown position, or has
            no matching advanced row.
    """
    advanced_by_key = {
        (row["season"], row["player_id"], row["team"]): row
        for row in advanced
        if row.get("lg", LEAGUE) == LEAGUE
    }

    players: list[OutputRow] = []
    for row in totals:
        if not _in_scope(row, last_season) or row["team"].endswith("TM"):
            continue
        if _number(row, "mp") < MIN_MINUTES:
            continue
        players.append(_player_row(row, advanced_by_key))

    team_rows = [
        _team_row(row)
        for row in teams
        if _in_scope(row, last_season) and row["abbreviation"] not in MISSING
    ]

    players.sort(key=lambda r: (int(r["season"]), r["team"], r["player_id"]))
    team_rows.sort(key=lambda r: (int(r["season"]), r["team"]))
    return players, team_rows


def validate(
    players: Sequence[OutputRow], teams: Sequence[OutputRow], min_roster: int = MIN_ROSTER
) -> None:
    """Check the built rows are consistent enough for the game to use.

    Args:
        players: Player rows from :func:`build`.
        teams: Team rows from :func:`build`.
        min_roster: The fewest players a team-season may have (the draft needs 8).

    Raises:
        DataError: On a duplicate card or team-season, a player whose team-season is
            missing, or a roster smaller than ``min_roster``.
    """
    team_keys = Counter((row["team"], row["season"]) for row in teams)
    duplicate_teams = [key for key, count in team_keys.items() if count > 1]
    if duplicate_teams:
        raise DataError(f"duplicate team-seasons: {duplicate_teams[:5]}")

    cards = Counter((row["player_id"], row["season"], row["team"]) for row in players)
    duplicate_cards = [key for key, count in cards.items() if count > 1]
    if duplicate_cards:
        raise DataError(f"duplicate player rows: {duplicate_cards[:5]}")

    roster_sizes = Counter((row["team"], row["season"]) for row in players)
    orphans = [key for key in roster_sizes if key not in team_keys]
    if orphans:
        raise DataError(f"players on team-seasons with no team row: {orphans[:5]}")

    small = [key for key in team_keys if roster_sizes[key] < min_roster]
    if small:
        raise DataError(f"team-seasons with fewer than {min_roster} players: {small[:5]}")


def _in_scope(row: SourceRow, last_season: int) -> bool:
    return row["lg"] == LEAGUE and FIRST_SEASON <= int(row["season"]) <= last_season


def _value(row: SourceRow, column: str) -> str:
    value = row[column]
    if value in MISSING:
        raise DataError(
            f"missing {column!r} for {row.get('player_id') or row.get('team')} in {row['season']}"
        )
    return value


def _number(row: SourceRow, column: str) -> float:
    value = _value(row, column)
    try:
        return float(value)
    except ValueError as error:
        raise DataError(f"{column!r} is not a number: {value!r}") from error


def _player_row(
    row: SourceRow, advanced_by_key: Mapping[tuple[str, str, str], SourceRow]
) -> OutputRow:
    key = (row["season"], row["player_id"], row["team"])
    extra = advanced_by_key.get(key)
    if extra is None:
        raise DataError(f"no advanced row for {key}")

    position = _value(row, "pos")
    if position not in POSITIONS:
        raise DataError(f"unknown position {position!r} for {key}")

    games = int(_number(row, "g"))
    out: OutputRow = {
        "player_id": row["player_id"],
        "name": _value(row, "player"),
        "season": row["season"],
        "team": row["team"],
        "position": position,
        "age": str(int(_number(row, "age"))),
        "games": str(games),
        "minutes_total": str(int(_number(row, "mp"))),
    }
    for column, source in PER_GAME_COLUMNS.items():
        out[column] = f"{_number(row, source) / games:.1f}"
    for column, source in ADVANCED_COLUMNS.items():
        _number(extra, source)  # fail loudly on a missing or malformed value
        out[column] = extra[source]
    return out


def _team_row(row: SourceRow) -> OutputRow:
    _number(row, "n_rtg")
    return {
        "team": row["abbreviation"],
        "season": row["season"],
        "name": _value(row, "team").rstrip("*"),
        "wins": str(int(_number(row, "w"))),
        "losses": str(int(_number(row, "l"))),
        "net_rating": row["n_rtg"],
    }


def _download(name: str) -> Path:
    path = CACHE_DIR / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = BASE_URL + urllib.parse.quote(name)
        print(f"Downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as response:
            path.write_bytes(response.read())
    return path


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _write(path: Path, columns: Sequence[str], rows: Iterable[OutputRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> None:
    """Download the source files, build the dataset and write the bundled CSVs.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Raises:
        DataError: If the output fails validation or, for the default last season, does
            not have the expected number of rows.
    """
    parser = argparse.ArgumentParser(description="Build the bundled NBA dataset.")
    parser.add_argument("--last-season", type=int, default=DEFAULT_LAST_SEASON)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    players, teams = build(
        _read(_download(TOTALS_FILE)),
        _read(_download(ADVANCED_FILE)),
        _read(_download(TEAMS_FILE)),
        args.last_season,
    )
    validate(players, teams)
    if args.last_season == DEFAULT_LAST_SEASON and (
        len(teams) != EXPECTED_TEAM_SEASONS or len(players) != EXPECTED_PLAYER_ROWS
    ):
        raise DataError(
            f"expected {EXPECTED_TEAM_SEASONS} team-seasons and {EXPECTED_PLAYER_ROWS} players,"
            f" got {len(teams)} and {len(players)}"
        )

    _write(args.output / "players.csv", PLAYER_COLUMNS, players)
    _write(args.output / "teams.csv", TEAM_COLUMNS, teams)
    print(f"Wrote {len(players)} player rows and {len(teams)} team-seasons to {args.output}")


if __name__ == "__main__":
    main()
