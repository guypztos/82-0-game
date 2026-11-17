import pytest

from tools.build_dataset import PLAYER_COLUMNS, TEAM_COLUMNS, DataError, build, validate


def totals_row(**overrides: object) -> dict[str, str]:
    row = {
        "season": "2016",
        "lg": "NBA",
        "player": "Stephen Curry",
        "player_id": "curryst01",
        "age": "27",
        "team": "GSW",
        "pos": "PG",
        "g": "79",
        "mp": "2700",
        "trb": "430",
        "ast": "527",
        "stl": "169",
        "blk": "15",
        "tov": "262",
        "pts": "2375",
    }
    return row | {key: str(value) for key, value in overrides.items()}


def advanced_row(**overrides: object) -> dict[str, str]:
    row = {
        "season": "2016",
        "lg": "NBA",
        "player_id": "curryst01",
        "team": "GSW",
        "ts_percent": "0.669",
        "trb_percent": "8.6",
        "ast_percent": "33.7",
        "usg_percent": "32.6",
        "obpm": "10.3",
        "dbpm": "1.6",
    }
    return row | {key: str(value) for key, value in overrides.items()}


def team_row(**overrides: object) -> dict[str, str]:
    row = {
        "season": "2016",
        "lg": "NBA",
        "team": "Golden State Warriors",
        "abbreviation": "GSW",
        "w": "73",
        "l": "9",
        "n_rtg": "10.7",
    }
    return row | {key: str(value) for key, value in overrides.items()}


def test_player_row_has_per_game_and_copied_values() -> None:
    players, _ = build([totals_row()], [advanced_row()], [team_row()])

    assert players == [
        {
            "player_id": "curryst01",
            "name": "Stephen Curry",
            "season": "2016",
            "team": "GSW",
            "position": "PG",
            "age": "27",
            "games": "79",
            "minutes_total": "2700",
            "points": "30.1",
            "rebounds": "5.4",
            "assists": "6.7",
            "steals": "2.1",
            "blocks": "0.2",
            "turnovers": "3.3",
            "true_shooting": "0.669",
            "usage": "32.6",
            "assist_pct": "33.7",
            "rebound_pct": "8.6",
            "obpm": "10.3",
            "dbpm": "1.6",
        }
    ]
    assert tuple(players[0]) == PLAYER_COLUMNS


def test_team_row() -> None:
    _, teams = build([], [], [team_row()])

    assert teams == [
        {
            "team": "GSW",
            "season": "2016",
            "name": "Golden State Warriors",
            "wins": "73",
            "losses": "9",
            "net_rating": "10.7",
        }
    ]
    assert tuple(teams[0]) == TEAM_COLUMNS


def test_traded_player_keeps_only_per_team_rows() -> None:
    totals = [
        totals_row(player_id="hardeja01", team="2TM", mp="2400"),
        totals_row(player_id="hardeja01", team="HOU", mp="800"),
        totals_row(player_id="hardeja01", team="BRK", mp="1600"),
    ]
    advanced = [advanced_row(player_id="hardeja01", team=row["team"]) for row in totals]

    players, _ = build(totals, advanced, [])

    assert sorted(p["team"] for p in players) == ["BRK", "HOU"]


def test_seasons_outside_the_range_are_dropped() -> None:
    totals = [
        totals_row(season="1979"),
        totals_row(season="1980"),
        totals_row(season="2026"),
        totals_row(season="2027"),
    ]
    advanced = [advanced_row(season=row["season"]) for row in totals]
    teams = [team_row(season=row["season"]) for row in totals]

    players, team_rows = build(totals, advanced, teams, last_season=2026)

    assert [p["season"] for p in players] == ["1980", "2026"]
    assert [t["season"] for t in team_rows] == ["1980", "2026"]


def test_other_leagues_are_dropped() -> None:
    players, teams = build([totals_row(lg="ABA")], [advanced_row(lg="ABA")], [team_row(lg="ABA")])

    assert players == []
    assert teams == []


def test_minimum_minutes_is_inclusive() -> None:
    totals = [
        totals_row(player_id="under", mp="399"),
        totals_row(player_id="exact", mp="400"),
    ]
    advanced = [advanced_row(player_id=row["player_id"]) for row in totals]

    players, _ = build(totals, advanced, [])

    assert [p["player_id"] for p in players] == ["exact"]


def test_league_average_rows_are_dropped_and_stars_stripped() -> None:
    teams = [
        team_row(team="League Average", abbreviation="NA", w="NA", l="NA", n_rtg="NA"),
        team_row(team="Boston Celtics*", abbreviation="BOS"),
    ]

    _, team_rows = build([], [], teams)

    assert [t["name"] for t in team_rows] == ["Boston Celtics"]


def test_rows_are_sorted() -> None:
    totals = [
        totals_row(season="2017", team="AAA", player_id="z"),
        totals_row(season="2016", team="BBB", player_id="b"),
        totals_row(season="2016", team="BBB", player_id="a"),
        totals_row(season="2016", team="AAA", player_id="c"),
    ]
    advanced = [advanced_row(**{k: r[k] for k in ("season", "team", "player_id")}) for r in totals]
    teams = [
        team_row(season="2017", abbreviation="AAA"),
        team_row(season="2016", abbreviation="BBB"),
        team_row(season="2016", abbreviation="AAA"),
    ]

    players, team_rows = build(totals, advanced, teams)

    assert [(p["season"], p["team"], p["player_id"]) for p in players] == [
        ("2016", "AAA", "c"),
        ("2016", "BBB", "a"),
        ("2016", "BBB", "b"),
        ("2017", "AAA", "z"),
    ]
    assert [(t["season"], t["team"]) for t in team_rows] == [
        ("2016", "AAA"),
        ("2016", "BBB"),
        ("2017", "AAA"),
    ]


def test_missing_advanced_row_fails() -> None:
    with pytest.raises(DataError, match="no advanced row"):
        build([totals_row()], [], [])


def test_advanced_rows_from_other_leagues_are_not_matched() -> None:
    with pytest.raises(DataError, match="no advanced row"):
        build([totals_row()], [advanced_row(lg="ABA")], [])


@pytest.mark.parametrize("column", ["tov", "age", "pts", "player"])
def test_missing_value_in_a_kept_row_fails(column: str) -> None:
    with pytest.raises(DataError, match="missing"):
        build([totals_row(**{column: "NA"})], [advanced_row()], [])


def test_missing_advanced_value_fails() -> None:
    with pytest.raises(DataError, match="missing 'obpm'"):
        build([totals_row()], [advanced_row(obpm="NA")], [])


def test_malformed_number_fails() -> None:
    with pytest.raises(DataError, match="not a number"):
        build([totals_row(pts="lots")], [advanced_row()], [])


def test_unknown_position_fails() -> None:
    with pytest.raises(DataError, match="unknown position"):
        build([totals_row(pos="G-F")], [advanced_row()], [])


def test_missing_net_rating_fails() -> None:
    with pytest.raises(DataError, match="missing 'n_rtg'"):
        build([], [], [team_row(n_rtg="NA")])


class TestValidate:
    @staticmethod
    def roster(team: str = "GSW", size: int = 8) -> list[dict[str, str]]:
        return [{"player_id": f"p{i}", "season": "2016", "team": team} for i in range(size)]

    def test_valid_data_passes(self) -> None:
        validate(self.roster(), [{"team": "GSW", "season": "2016"}])

    def test_small_roster_fails(self) -> None:
        with pytest.raises(DataError, match="fewer than 8"):
            validate(self.roster(size=7), [{"team": "GSW", "season": "2016"}])

    def test_team_with_no_players_fails(self) -> None:
        teams = [{"team": "GSW", "season": "2016"}, {"team": "BOS", "season": "2016"}]

        with pytest.raises(DataError, match="fewer than 8"):
            validate(self.roster(), teams)

    def test_player_on_missing_team_fails(self) -> None:
        with pytest.raises(DataError, match="no team row"):
            validate(self.roster() + self.roster(team="BOS"), [{"team": "GSW", "season": "2016"}])

    def test_duplicate_player_fails(self) -> None:
        players = self.roster()
        players.append(players[0])

        with pytest.raises(DataError, match="duplicate player"):
            validate(players, [{"team": "GSW", "season": "2016"}])

    def test_duplicate_team_fails(self) -> None:
        teams = [{"team": "GSW", "season": "2016"}] * 2

        with pytest.raises(DataError, match="duplicate team-seasons"):
            validate(self.roster(), teams)
