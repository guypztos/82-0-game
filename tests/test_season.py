import random
import statistics

import pytest

from eighty_two_o.config import SimConfig
from eighty_two_o.data.repository import Dataset
from eighty_two_o.rating import rate_team
from eighty_two_o.season import GameResult, SeasonResult, build_schedule, simulate_season
from tests.factories import make_dataset, make_team
from tests.test_rating import ALL_TIME, rate_ids

SEEDS = range(2000)


@pytest.fixture(scope="module")
def big() -> Dataset:
    """A synthetic dataset with enough team-seasons for an 82-game schedule."""
    return make_dataset(team_count=100, roster_size=8)


def game(number: int, won: bool, team_points: int, opponent_points: int) -> GameResult:
    return GameResult(
        number=number,
        opponent=make_team(team=f"O{number:02d}"),
        home=number % 2 == 0,
        won=won,
        team_points=team_points,
        opponent_points=opponent_points,
    )


class TestSchedule:
    def test_82_distinct_opponents_half_at_home(self, big: Dataset) -> None:
        schedule = build_schedule(big, random.Random(1))

        assert len(schedule) == 82
        assert len({opponent.key for opponent, _ in schedule}) == 82
        assert sum(home for _, home in schedule) == 41

    def test_order_is_shuffled(self, big: Dataset) -> None:
        homes = [home for _, home in build_schedule(big, random.Random(1))]

        assert homes != sorted(homes, reverse=True)

    def test_length_comes_from_the_config(self, big: Dataset) -> None:
        assert len(build_schedule(big, random.Random(1), SimConfig(games=10))) == 10


class TestSimulateSeason:
    def test_same_seed_gives_the_same_season(self, big: Dataset) -> None:
        assert simulate_season(5.0, big, seed=3) == simulate_season(5.0, big, seed=3)

    def test_different_seeds_differ(self, big: Dataset) -> None:
        assert simulate_season(5.0, big, seed=3) != simulate_season(5.0, big, seed=4)

    def test_games_are_numbered_in_order(self, big: Dataset) -> None:
        season = simulate_season(0.0, big, seed=1)

        assert [g.number for g in season.games] == list(range(1, 83))

    def test_scores_are_consistent(self, big: Dataset) -> None:
        for seed in range(50):
            for result in simulate_season(10.0, big, seed).games:
                assert result.team_points != result.opponent_points
                assert result.won == (result.team_points > result.opponent_points)
                assert 60 <= result.team_points <= 170
                assert 60 <= result.opponent_points <= 170

    def test_better_teams_win_more(self, big: Dataset) -> None:
        def average_wins(net: float) -> float:
            return statistics.fmean(simulate_season(net, big, seed).wins for seed in range(50))

        assert average_wins(-10) < average_wins(0) < average_wins(10)

    def test_huge_blowouts_keep_a_plausible_losing_score(self, big: Dataset) -> None:
        season = simulate_season(80.0, big, seed=1)

        assert season.perfect
        assert min(g.opponent_points for g in season.games) >= 70


class TestSeasonResult:
    def test_summary_properties(self) -> None:
        season = SeasonResult(
            games=(
                game(1, True, 110, 100),
                game(2, True, 120, 90),
                game(3, False, 95, 101),
                game(4, True, 101, 100),
                game(5, True, 99, 98),
                game(6, True, 105, 104),
                game(7, False, 80, 110),
                game(8, True, 130, 100),
            )
        )

        assert (season.wins, season.losses, season.record) == (6, 2, "6-2")
        assert not season.perfect
        assert season.first_loss == season.games[2]
        assert season.longest_win_streak == 3
        assert season.biggest_win == season.games[1]
        assert season.worst_loss == season.games[6]
        assert [team.team for team in season.losses_to] == ["O03", "O07"]
        assert season.games[6].margin == -30

    def test_perfect_season(self) -> None:
        season = SeasonResult(games=(game(1, True, 100, 90), game(2, True, 100, 99)))

        assert season.perfect
        assert season.first_loss is None
        assert season.worst_loss is None
        assert season.losses_to == ()
        assert season.longest_win_streak == 2

    def test_winless_season(self) -> None:
        season = SeasonResult(games=(game(1, False, 90, 100),))

        assert season.biggest_win is None
        assert season.longest_win_streak == 0

    def test_round_trips_through_json(self, big: Dataset) -> None:
        season = simulate_season(3.0, big, seed=8)

        assert SeasonResult.model_validate_json(season.model_dump_json()) == season


class TestPinnedSeasons:
    """Averages over seeds 0..1999, measured when the constants were validated."""

    @staticmethod
    def run(net: float, dataset: Dataset) -> tuple[float, float]:
        seasons = [simulate_season(net, dataset, seed) for seed in SEEDS]
        average_wins = statistics.fmean(season.wins for season in seasons)
        perfect_share = sum(season.perfect for season in seasons) / len(seasons)
        return average_wins, perfect_share

    @staticmethod
    def top_eight_net(dataset: Dataset, team_key: str) -> float:
        roster = dataset.roster(team_key)
        return rate_team(roster[:5], roster[5:8]).net

    def test_all_time_lineup(self, dataset: Dataset) -> None:
        average_wins, perfect_share = self.run(rate_ids(dataset, ALL_TIME).net, dataset)

        assert average_wins >= 80.8
        assert 0.40 <= perfect_share <= 0.56

    def test_1996_bulls(self, dataset: Dataset) -> None:
        average_wins, perfect_share = self.run(self.top_eight_net(dataset, "CHI:1996"), dataset)

        assert 70.5 <= average_wins <= 75.5
        assert perfect_share < 0.005

    def test_2012_bobcats(self, dataset: Dataset) -> None:
        average_wins, perfect_share = self.run(self.top_eight_net(dataset, "CHA:2012"), dataset)

        assert 8 <= average_wins <= 15
        assert perfect_share == 0
