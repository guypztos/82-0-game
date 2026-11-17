import pytest

from eighty_two_o.data.models import Position
from eighty_two_o.data.repository import Dataset, load_dataset, parse_player, parse_team
from tests.factories import make_player, make_team

# Every card the pinned rating and season tests rely on.
PINNED_CARDS = (
    "curryst01:2016:GSW",
    "jordami01:1991:CHI",
    "jamesle01:2013:MIA",
    "duncati01:2003:SAS",
    "onealsh01:2000:LAL",
    "johnsma02:1987:LAL",
    "birdla01:1986:BOS",
    "olajuha01:1994:HOU",
    "robinda01:1994:SAS",
    "ewingpa01:1990:NYK",
    "jokicni01:2022:DEN",
    "jordami01:1987:CHI",
    "bryanko01:2006:LAL",
    "hardeja01:2019:HOU",
    "iversal01:2001:PHI",
    "westbru01:2017:OKC",
    "duranke01:2014:OKC",
    "mcgratr01:2003:ORL",
    "wadedw01:2009:MIA",
)


class TestDatasetIndexing:
    def test_rosters_are_sorted_by_minutes_then_id(self) -> None:
        players = [
            make_player(player_id="b", minutes_total=1000),
            make_player(player_id="a", minutes_total=1000),
            make_player(player_id="c", minutes_total=3000),
        ]
        dataset = Dataset(players, [make_team()])

        assert [p.player_id for p in dataset.roster("TST:2016")] == ["c", "a", "b"]

    def test_team_seasons_are_sorted_by_season_then_team(self) -> None:
        teams = [
            make_team(team="BBB", season=2016),
            make_team(team="AAA", season=2016),
            make_team(team="ZZZ", season=2015),
        ]
        dataset = Dataset([], teams)

        assert [t.key for t in dataset.team_seasons] == ["ZZZ:2015", "AAA:2016", "BBB:2016"]

    def test_lookups(self) -> None:
        player = make_player()
        team = make_team()
        dataset = Dataset([player], [team])

        assert dataset.card(player.card_id) == player
        assert dataset.team(team.key) == team
        assert dataset.players == (player,)

    def test_team_without_players_has_an_empty_roster(self) -> None:
        dataset = Dataset([], [make_team()])

        assert dataset.roster("TST:2016") == ()

    @pytest.mark.parametrize("method", ["card", "team", "roster"])
    def test_unknown_ids_raise_key_error(self, method: str) -> None:
        dataset = Dataset([], [make_team()])

        with pytest.raises(KeyError):
            getattr(dataset, method)("nope")

    def test_duplicate_team_season_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate team-season"):
            Dataset([], [make_team(), make_team()])

    def test_duplicate_card_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate card"):
            Dataset([make_player(), make_player()], [make_team()])

    def test_card_without_team_season_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="has no team-season"):
            Dataset([make_player(team="XXX")], [make_team()])


def test_parse_player_reads_position_names_and_numbers() -> None:
    row = {
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

    player = parse_player(row)

    assert player.position is Position.PG
    assert player.season == 2016
    assert player.obpm == pytest.approx(10.3)


def test_parse_team() -> None:
    row = {
        "team": "GSW",
        "season": "2016",
        "name": "Golden State Warriors",
        "wins": "73",
        "losses": "9",
        "net_rating": "10.7",
    }

    assert parse_team(row) == make_team(
        team="GSW", name="Golden State Warriors", wins=73, losses=9, net_rating=10.7
    )


class TestBundledData:
    def test_load_dataset_is_cached(self, dataset: Dataset) -> None:
        assert load_dataset() is dataset

    def test_expected_counts(self, dataset: Dataset) -> None:
        assert len(dataset.team_seasons) == 1314
        assert len(dataset.players) == 15928

    def test_seasons_cover_1980_to_2026(self, dataset: Dataset) -> None:
        seasons = {team.season for team in dataset.team_seasons}

        assert min(seasons) == 1980
        assert max(seasons) == 2026

    def test_every_roster_has_at_least_eight_players(self, dataset: Dataset) -> None:
        sizes = {team.key: len(dataset.roster(team.key)) for team in dataset.team_seasons}

        assert min(sizes.values()) == 8
        assert sizes["DET:1988"] == 8

    def test_card_ids_are_unique(self, dataset: Dataset) -> None:
        ids = [p.card_id for p in dataset.players]

        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("card_id", PINNED_CARDS)
    def test_pinned_cards_exist(self, dataset: Dataset, card_id: str) -> None:
        assert dataset.card(card_id).card_id == card_id

    @pytest.mark.parametrize("team_key", ["CHI:1996", "GSW:2016", "CHA:2012"])
    def test_pinned_team_seasons_exist(self, dataset: Dataset, team_key: str) -> None:
        assert len(dataset.roster(team_key)) >= 8

    def test_known_values(self, dataset: Dataset) -> None:
        curry = dataset.card("curryst01:2016:GSW")
        warriors = dataset.team("GSW:2016")

        assert curry.name == "Stephen Curry"
        assert curry.position is Position.PG
        assert curry.obpm == pytest.approx(10.3)
        assert curry.usage == pytest.approx(32.6)
        assert warriors.record == "73-9"
        assert warriors.label == "2015-16 Golden State Warriors"

    def test_minimum_minutes(self, dataset: Dataset) -> None:
        assert min(p.minutes_total for p in dataset.players) >= 400

    def test_traded_players_appear_on_each_team(self, dataset: Dataset) -> None:
        # Pau Gasol was traded from Memphis to the Lakers in February 2008.
        gasol_2008 = [p for p in dataset.players if p.player_id == "gasolpa01" and p.season == 2008]

        assert {p.team for p in gasol_2008} == {"MEM", "LAL"}
