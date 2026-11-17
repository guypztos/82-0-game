import re

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape

from eighty_two_o.data.repository import Dataset
from eighty_two_o.game import Mode, Phase
from eighty_two_o.store import InMemoryStore
from eighty_two_o.sweep.draft import board
from eighty_two_o.sweep.game import SweepGame
from eighty_two_o.sweep.models import Slot
from eighty_two_o.sweep.repository import SweepDataset
from eighty_two_o.sweep.season import CarResult, RaceResult, SweepSeason
from eighty_two_o.web.app import create_app
from eighty_two_o.web.routes import CREDIT
from eighty_two_o.web.sweep_routes import (
    SWEEP_CREDIT,
    beaten_by,
    car_result_line,
    driver_line,
    part_line,
    part_name,
    sweep_verdict,
)
from tests.factories import make_car, make_driver

RATING = 'class="rating"'


class Harness:
    """A test client plus direct access to the Clean Sweep store, to look up legal moves."""

    def __init__(self, dataset: Dataset, sweep_dataset: SweepDataset) -> None:
        self.dataset = sweep_dataset
        self.store = InMemoryStore[SweepGame]()
        app = create_app(dataset, sweep_dataset=sweep_dataset, sweep_store=self.store)
        self.client = TestClient(app, follow_redirects=False)

    def start(self, mode: str = "rookie", seed: int | str = 42) -> str:
        response = self.client.post("/sweep/games", data={"mode": mode, "seed": str(seed)})
        assert response.status_code == 303
        location: str = response.headers["location"]
        assert location.startswith("/sweep/games/")
        return location.removeprefix("/sweep/games/")

    def game(self, game_id: str) -> SweepGame:
        game = self.store.get(game_id)
        assert game is not None
        return game

    def first_legal(self, game_id: str) -> str:
        b = board(self.game(game_id).draft, self.dataset)
        part = next((o.slot.value for o in b.parts if o.available), None)
        if part is not None:
            return part
        return f"driver:{next(o.card.card_id for o in b.drivers if o.available)}"

    def pick(self, game_id: str, item: str, pick_number: int | None = None) -> int:
        number = self.game(game_id).draft.picks_made if pick_number is None else pick_number
        response = self.client.post(
            f"/sweep/games/{game_id}/pick", data={"item": item, "pick_number": str(number)}
        )
        status: int = response.status_code
        return status

    def draft_all(self, game_id: str) -> None:
        while self.game(game_id).phase is Phase.DRAFT:
            assert self.pick(game_id, self.first_legal(game_id)) == 303

    def reroll(self, game_id: str) -> int:
        number = self.game(game_id).draft.picks_made
        response = self.client.post(
            f"/sweep/games/{game_id}/reroll", data={"pick_number": str(number)}
        )
        status: int = response.status_code
        return status

    def lock(self, game_id: str, reserve: str | None = None) -> int:
        chosen = self.game(game_id).draft.drivers[-1].card_id if reserve is None else reserve
        response = self.client.post(f"/sweep/games/{game_id}/lineup", data={"reserve": chosen})
        status: int = response.status_code
        return status

    def play(self, mode: str = "rookie", seed: int = 42) -> str:
        game_id = self.start(mode, seed)
        self.draft_all(game_id)
        assert self.lock(game_id) == 303
        return game_id

    def page(self, game_id: str) -> str:
        response = self.client.get(f"/sweep/games/{game_id}")
        assert response.status_code == 200
        text: str = response.text
        return text


@pytest.fixture
def web(dataset: Dataset, sweep_dataset: SweepDataset) -> Harness:
    return Harness(dataset, sweep_dataset)


class TestBasics:
    def test_home_offers_both_games(self, web: Harness) -> None:
        page = web.client.get("/").text

        assert 'action="/games"' in page
        assert 'action="/sweep/games"' in page
        assert "Clean Sweep" in page
        assert str(escape(SWEEP_CREDIT)) in page

    def test_credit_only_on_sweep_pages(self, web: Harness) -> None:
        sweep_page = web.page(web.start())
        response = web.client.post("/games", data={"mode": "rookie", "seed": "1"})
        basketball_page = web.client.get(response.headers["location"]).text

        assert str(escape(SWEEP_CREDIT)) in sweep_page
        assert str(escape(CREDIT)) not in sweep_page
        assert str(escape(SWEEP_CREDIT)) not in basketball_page
        assert "Clean Sweep" not in basketball_page

    def test_unknown_game_is_a_404(self, web: Harness) -> None:
        assert web.client.get("/sweep/games/nope").status_code == 404
        for action in ("pick", "reroll", "lineup"):
            data = {"item": "engine", "pick_number": "0", "reserve": "x"}
            assert web.client.post(f"/sweep/games/nope/{action}", data=data).status_code == 404

    def test_random_seed_when_left_empty(self, web: Harness) -> None:
        assert web.game(web.start(seed="")).phase is Phase.DRAFT

    @pytest.mark.parametrize(("mode", "seed"), [("expert", "1"), ("rookie", "abc")])
    def test_invalid_input_is_a_400(self, web: Harness, mode: str, seed: str) -> None:
        response = web.client.post("/sweep/games", data={"mode": mode, "seed": seed})

        assert response.status_code == 400
        assert "Choose Rookie or Legend" in response.text


class TestRookieGame:
    def test_whole_game_over_http(self, web: Harness) -> None:
        game_id = web.start()
        draft_page = web.page(game_id)
        assert 'Pick <span class="led">1</span> of 7' in draft_page
        assert "Pick 1 of 7 · Clean Sweep" in draft_page
        assert RATING in draft_page
        assert "Reroll team (2 left)" in draft_page

        web.draft_all(game_id)
        lineup_page = web.page(game_id)
        assert "Start the season" in lineup_page
        assert lineup_page.count('type="radio"') == 3
        assert RATING in lineup_page
        last = web.game(game_id).draft.drivers[-1].card_id
        assert re.search(rf'value="{re.escape(last)}"[^>]*\s+checked', lineup_page)

        assert web.lock(game_id) == 303
        season_page = web.page(game_id)
        game = web.game(game_id)
        assert game.season is not None
        assert f'<span class="led">{game.season.record}</span>' in season_page
        assert season_page.count("data-game ") == 20
        assert 'data-unit="Race"' in season_page
        assert str(escape(sweep_verdict(game.season.wins, 20))) in season_page
        assert "For scale: the strongest real car, the 1992 Williams, is +7.52." in season_page
        assert f"Seed {game.seed}" in season_page
        assert 'action="/sweep/games"' in season_page

    def test_same_seed_and_choices_give_the_same_season(self, web: Harness) -> None:
        first = web.game(web.play(seed=7)).season
        second = web.game(web.play(seed=7)).season

        assert first is not None
        assert first == second

    def test_reserve_choice(self, web: Harness) -> None:
        game_id = web.start(seed=8)
        web.draft_all(game_id)
        first = web.game(game_id).draft.drivers[0]

        assert web.lock(game_id, "not-a-driver") == 400
        assert web.lock(game_id, first.card_id) == 303
        team = web.game(game_id).team
        assert team is not None
        assert team.reserve == first

    def test_season_page_shows_losses(self, web: Harness) -> None:
        for seed in range(5):
            game_id = web.play(seed=seed)
            season = web.game(game_id).season
            assert season is not None
            if season.first_loss is not None:
                page = web.page(game_id)
                assert "First defeat" in page
                assert "Who beat you" in page
                return
        pytest.fail("every season was a clean sweep")


class TestLegendGame:
    def test_no_numbers_before_the_season(self, web: Harness) -> None:
        game_id = web.start(mode="legend", seed=3)
        stat_words = (" starts", "mechanical retirement", " wins across", "Real season", "Rating")
        while web.game(game_id).phase is Phase.DRAFT:
            page = web.page(game_id)
            assert RATING not in page
            assert not any(word in page for word in stat_words)
            names = re.findall(
                r'class="card-name">([^<]+) \(\d{4}\)</span>', page.split("Your team")[0]
            )
            assert names == sorted(names)
            assert web.pick(game_id, web.first_legal(game_id)) == 303

        lineup_page = web.page(game_id)
        assert RATING not in lineup_page
        assert " starts" not in lineup_page

        assert web.lock(game_id) == 303
        season_page = web.page(game_id)
        assert RATING in season_page
        assert " starts" in season_page

    def test_drivers_are_alphabetical(self, web: Harness, sweep_dataset: SweepDataset) -> None:
        # Find a Legend roll whose roster order is not alphabetical.
        for seed in range(50):
            game_id = web.start(mode="legend", seed=seed)
            key = web.game(game_id).draft.current_roll
            assert key is not None
            roster = [d.name for d in sweep_dataset.roster(key)]
            if roster != sorted(roster):
                page = web.page(game_id)
                positions = [page.index(f">{name} (") for name in sorted(roster)]
                assert positions == sorted(positions)
                return
        pytest.fail("no roll with a non-alphabetical roster")


class TestErrors:
    def test_reroll_limit(self, web: Harness) -> None:
        game_id = web.start()

        assert web.reroll(game_id) == 303
        assert web.reroll(game_id) == 303
        assert "Reroll team (0 left)" in web.page(game_id)
        response = web.client.post(f"/sweep/games/{game_id}/reroll", data={"pick_number": "0"})
        assert response.status_code == 400
        assert "no rerolls left" in response.text

    def test_filled_slot(self, web: Harness) -> None:
        game_id = web.start()
        assert web.pick(game_id, "engine") == 303

        response = web.client.post(
            f"/sweep/games/{game_id}/pick", data={"item": "engine", "pick_number": "1"}
        )
        assert response.status_code == 400
        assert "engine slot is already filled" in response.text

    def test_stale_forms_change_nothing(self, web: Harness) -> None:
        game_id = web.start()
        assert web.pick(game_id, "engine") == 303
        before = web.game(game_id)

        assert web.pick(game_id, "chassis", pick_number=0) == 303
        response = web.client.post(f"/sweep/games/{game_id}/reroll", data={"pick_number": "0"})
        assert response.status_code == 303
        assert web.lock(game_id, "anything") == 303  # not the lineup phase yet
        assert web.game(game_id) == before

        web.draft_all(game_id)
        lineup = web.game(game_id)
        assert web.pick(game_id, "engine", pick_number=7) == 303
        assert web.game(game_id) == lineup


class TestHelpers:
    @pytest.mark.parametrize(
        ("wins", "expected"),
        [
            (20, "CLEAN SWEEP. 20 wins from 20."),
            (19, "One race short of perfect."),
            (15, "A dominant champion, but not a clean sweep."),
            (10, "A title contender."),
            (4, "A race winner."),
            (1, "A few good Sundays."),
            (0, "Winless."),
        ],
    )
    def test_verdict(self, wins: int, expected: str) -> None:
        assert sweep_verdict(wins, 20) == expected

    def test_part_lines(self) -> None:
        car = make_car(
            constructor_id="red-bull",
            name="Red Bull",
            year=2023,
            chassis_name="RB19",
            engine_name="Honda",
            engine_badge="Honda RBPT",
            engine_wins=21,
            engine_teams=2,
            wins=21,
            poles=14,
            podiums=30,
            races=22,
            mechanical_retirements=1,
            starts=44,
            pit_rank=1,
        )

        assert part_name(Slot.ENGINE, car) == "2023 Honda"
        assert part_name(Slot.CHASSIS, car) == "2023 Red Bull RB19"
        assert part_name(Slot.PIT_CREW, car) == "2023 Red Bull"
        assert part_line(Slot.ENGINE, car) == "21 wins across 2 teams, badged Honda RBPT"
        assert part_line(Slot.CHASSIS, car) == "21 wins, 14 poles, 30 podiums in 22 races"
        assert part_line(Slot.RELIABILITY, car) == "1 mechanical retirement in 44 starts"
        assert part_line(Slot.PIT_CREW, car) == "1st fastest pit stops that season"
        for rank, text in [(2, "2nd"), (3, "3rd"), (11, "11th"), (12, "12th"), (22, "22nd")]:
            assert part_line(Slot.PIT_CREW, car.model_copy(update={"pit_rank": rank})).startswith(
                text
            )
        unrated = car.model_copy(update={"pit_rank": None, "engine_badge": "Honda"})
        assert part_line(Slot.PIT_CREW, unrated) == "No pit-stop timing before 1994: rated average"
        assert part_line(Slot.ENGINE, unrated) == "21 wins across 2 teams"

    def test_driver_and_result_lines(self) -> None:
        driver = make_driver(starts=1, wins=0, podiums=2, poles=1)

        assert driver_line(driver) == "1 start, 0 wins, 2 podiums, 1 pole"
        assert (
            car_result_line(CarResult(driver="A", reserve=False, position=1, retirement=None))
            == "P1 A"
        )
        out = CarResult(driver="B", reserve=True, position=None, retirement="incident")
        assert car_result_line(out) == "B (reserve) out (incident)"

    def test_beaten_by(self) -> None:
        def race(number: int, winner: str | None) -> RaceResult:
            car = CarResult(driver="A", reserve=False, position=None, retirement="mechanical")
            return RaceResult(
                number=number,
                year=2000,
                won=False,
                winner=winner,
                winner_car=None if winner is None else "2000 Ferrari",
                cars=(car, car),
                finishers=0 if winner is None else 10,
            )

        season = SweepSeason(races=(race(1, "X"), race(2, None), race(3, "X")))

        assert beaten_by(season) == [("X, 2000 Ferrari", 2), ("Nobody finished", 1)]


def test_mode_badge(web: Harness) -> None:
    assert f"{Mode.LEGEND.value.capitalize()} mode" in web.page(web.start(mode="legend"))


class TestStartOver:
    def test_offered_until_the_season_is_raced(self, web: Harness) -> None:
        game_id = web.start(mode="legend")
        restart = 'action="/sweep/games" class="restart"'
        assert restart in web.page(game_id)
        assert 'name="mode" value="legend"' in web.page(game_id)

        web.draft_all(game_id)
        assert restart in web.page(game_id)

        assert web.lock(game_id) == 303
        assert restart not in web.page(game_id)

    def test_starts_a_fresh_run_and_keeps_the_old_one(self, web: Harness) -> None:
        old_id = web.start(mode="legend", seed=5)
        assert web.pick(old_id, "engine") == 303
        before = web.game(old_id)

        response = web.client.post("/sweep/games", data={"mode": "legend"})
        new = web.game(response.headers["location"].removeprefix("/sweep/games/"))

        assert new.id != old_id
        assert new.mode is before.mode
        assert new.draft.picks_made == 0
        assert web.game(old_id) == before
