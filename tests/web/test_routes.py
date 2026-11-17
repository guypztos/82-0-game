import re

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape

from eighty_two_o.data.repository import Dataset
from eighty_two_o.draft import roster_view
from eighty_two_o.game import Game, InMemoryGameStore, Phase
from eighty_two_o.rating import TeamRating
from eighty_two_o.web.app import create_app
from eighty_two_o.web.routes import CREDIT, breakdown, verdict


class Harness:
    """A test client plus direct access to the store, to look up legal moves."""

    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset
        self.store = InMemoryGameStore()
        self.client = TestClient(create_app(dataset, self.store), follow_redirects=False)

    def start(self, mode: str = "rookie", seed: int | str = 42) -> str:
        response = self.client.post("/games", data={"mode": mode, "seed": str(seed)})
        assert response.status_code == 303
        location: str = response.headers["location"]
        assert location.startswith("/games/")
        return location.removeprefix("/games/")

    def game(self, game_id: str) -> Game:
        game = self.store.get(game_id)
        assert game is not None
        return game

    def pick_first_available(self, game_id: str) -> None:
        game = self.game(game_id)
        card_id = next(e.card.card_id for e in roster_view(game.draft, self.dataset) if e.available)
        response = self.client.post(
            f"/games/{game_id}/pick",
            data={"card_id": card_id, "pick_number": str(len(game.draft.picks))},
        )
        assert response.status_code == 303

    def draft_all(self, game_id: str) -> None:
        while self.game(game_id).phase is Phase.DRAFT:
            self.pick_first_available(game_id)

    def lock_first_five(self, game_id: str) -> None:
        starters = [card.card_id for card in self.game(game_id).draft.picks[:5]]
        response = self.client.post(f"/games/{game_id}/lineup", data={"starters": starters})
        assert response.status_code == 303

    def play(self, mode: str = "rookie", seed: int = 42) -> str:
        game_id = self.start(mode, seed)
        self.draft_all(game_id)
        self.lock_first_five(game_id)
        return game_id

    def page(self, game_id: str) -> str:
        response = self.client.get(f"/games/{game_id}")
        assert response.status_code == 200
        text: str = response.text
        return text


@pytest.fixture
def web(dataset: Dataset) -> Harness:
    return Harness(dataset)


class TestBasics:
    def test_home(self, web: Harness) -> None:
        response = web.client.get("/")

        assert response.status_code == 200
        assert "Rookie" in response.text
        assert "Legend" in response.text
        assert str(escape(CREDIT)) in response.text

    def test_healthz(self, web: Harness) -> None:
        assert web.client.get("/healthz").json() == {"status": "ok"}

    @pytest.mark.parametrize("path", ["/static/style.css", "/static/reveal.js"])
    def test_static_files(self, web: Harness, path: str) -> None:
        assert web.client.get(path).status_code == 200

    def test_create_app_defaults(self) -> None:
        client = TestClient(create_app())

        assert client.get("/healthz").status_code == 200


class TestCreateGame:
    def test_random_seed_when_left_empty(self, web: Harness) -> None:
        game_id = web.start(seed="")

        assert web.game(game_id).phase is Phase.DRAFT

    @pytest.mark.parametrize(
        ("mode", "seed"), [("expert", "1"), ("rookie", "abc"), ("legend", "1.5")]
    )
    def test_invalid_input_is_a_400(self, web: Harness, mode: str, seed: str) -> None:
        response = web.client.post("/games", data={"mode": mode, "seed": seed})

        assert response.status_code == 400
        assert "Choose Rookie or Legend" in response.text


class TestRookieGame:
    def test_whole_game_over_http(self, web: Harness) -> None:
        game_id = web.start()
        draft_page = web.page(game_id)
        assert 'Pick <span class="led">1</span> of 8' in draft_page
        assert "PPG" in draft_page

        web.draft_all(game_id)
        lineup_page = web.page(game_id)
        assert "Start the season" in lineup_page
        assert lineup_page.count('type="checkbox"') == 8

        web.lock_first_five(game_id)
        season_page = web.page(game_id)
        season = web.game(game_id).season
        assert season is not None
        assert f'<span class="led">{season.record}</span>' in season_page
        assert season_page.count("data-game ") == 82
        assert verdict(season.wins) in season_page
        assert "reveal.js" in season_page

    def test_same_seed_and_choices_give_the_same_record(self, web: Harness) -> None:
        first = web.game(web.play(seed=7)).season
        second = web.game(web.play(seed=7)).season

        assert first is not None
        assert second is not None
        assert first.record == second.record
        assert first == second

    def test_roster_is_in_minutes_order(self, web: Harness) -> None:
        game_id = web.start()
        game = web.game(game_id)
        assert game.draft.current_roll is not None
        names = [str(escape(p.name)) for p in web.dataset.roster(game.draft.current_roll)]

        page = web.page(game_id)

        assert [page.index(name) for name in names] == sorted(page.index(n) for n in names)


class TestLegendGame:
    def test_no_stats_before_the_lineup_is_locked(self, web: Harness) -> None:
        game_id = web.start(mode="legend", seed=3)
        game = web.game(game_id)
        assert game.draft.current_roll is not None
        roster = web.dataset.roster(game.draft.current_roll)

        draft_page = web.page(game_id)
        assert "PPG" not in draft_page
        for player in roster:
            assert f">{player.points:.1f}<" not in draft_page
        assert not re.search(r"\d+\.\d", draft_page)

        web.draft_all(game_id)
        lineup_page = web.page(game_id)
        assert "PPG" not in lineup_page
        assert not re.search(r"\d+\.\d", lineup_page)

        web.lock_first_five(game_id)
        season_page = web.page(game_id)
        assert "PPG" in season_page
        picks = web.game(game_id).draft.picks
        assert any(f">{p.points:.1f}<" in season_page for p in picks)

    def test_roster_is_alphabetical(self, web: Harness) -> None:
        game_id = web.start(mode="legend", seed=3)
        game = web.game(game_id)
        assert game.draft.current_roll is not None
        names = sorted(str(escape(p.name)) for p in web.dataset.roster(game.draft.current_roll))

        page = web.page(game_id)

        positions = [page.index(f'<td class="name">{name}</td>') for name in names]
        assert positions == sorted(positions)


class TestDraftActions:
    def test_reroll_changes_the_team(self, web: Harness) -> None:
        game_id = web.start()
        before = web.game(game_id).draft.current_roll

        response = web.client.post(f"/games/{game_id}/reroll", data={"pick_number": "0"})

        assert response.status_code == 303
        assert web.game(game_id).draft.current_roll != before
        assert "1 left" in web.page(game_id)

    def test_reroll_limit_is_a_400(self, web: Harness) -> None:
        game_id = web.start()
        for _ in range(2):
            web.client.post(f"/games/{game_id}/reroll", data={"pick_number": "0"})
        assert "disabled" in web.page(game_id)

        response = web.client.post(f"/games/{game_id}/reroll", data={"pick_number": "0"})

        assert response.status_code == 400
        assert "no rerolls left" in response.text

    def test_illegal_pick_is_a_400(self, web: Harness) -> None:
        game_id = web.start()

        response = web.client.post(
            f"/games/{game_id}/pick", data={"card_id": "nobody:1990:XXX", "pick_number": "0"}
        )

        assert response.status_code == 400
        assert "not on this roster" in response.text
        assert web.game(game_id).draft.picks == ()

    @pytest.mark.parametrize("action", ["pick", "reroll"])
    def test_stale_submission_changes_nothing(self, web: Harness, action: str) -> None:
        game_id = web.start()
        before = web.game(game_id)
        card_id = roster_view(before.draft, web.dataset)[0].card.card_id

        response = web.client.post(
            f"/games/{game_id}/{action}", data={"card_id": card_id, "pick_number": "5"}
        )

        assert response.status_code == 303
        assert web.game(game_id) == before

    @pytest.mark.parametrize("action", ["pick", "reroll"])
    def test_draft_actions_after_the_draft_change_nothing(self, web: Harness, action: str) -> None:
        game_id = web.start()
        web.draft_all(game_id)
        before = web.game(game_id)

        response = web.client.post(
            f"/games/{game_id}/{action}", data={"card_id": "x", "pick_number": "8"}
        )

        assert response.status_code == 303
        assert web.game(game_id) == before


class TestLineupActions:
    def test_wrong_number_of_starters_is_a_400(self, web: Harness) -> None:
        game_id = web.start()
        web.draft_all(game_id)
        four = [card.card_id for card in web.game(game_id).draft.picks[:4]]

        response = web.client.post(f"/games/{game_id}/lineup", data={"starters": four})

        assert response.status_code == 400
        assert "exactly 5 starters" in response.text

    def test_no_starters_checked_is_a_400(self, web: Harness) -> None:
        game_id = web.start()
        web.draft_all(game_id)

        response = web.client.post(f"/games/{game_id}/lineup")

        assert response.status_code == 400

    def test_lineup_before_the_draft_ends_changes_nothing(self, web: Harness) -> None:
        game_id = web.start()

        response = web.client.post(f"/games/{game_id}/lineup", data={"starters": ["a"]})

        assert response.status_code == 303
        assert web.game(game_id).phase is Phase.DRAFT

    def test_resubmitting_a_finished_lineup_changes_nothing(self, web: Harness) -> None:
        game_id = web.play()
        before = web.game(game_id)

        response = web.client.post(f"/games/{game_id}/lineup", data={"starters": ["a"]})

        assert response.status_code == 303
        assert web.game(game_id) == before


class TestNotFound:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/games/missing"),
            ("post", "/games/missing/pick"),
            ("post", "/games/missing/reroll"),
            ("post", "/games/missing/lineup"),
        ],
    )
    def test_unknown_game_is_a_404(self, web: Harness, method: str, path: str) -> None:
        data = {"card_id": "x", "pick_number": "0"} if method == "post" else None

        response = web.client.request(method.upper(), path, data=data)

        assert response.status_code == 404
        assert "Start a new game" in response.text


@pytest.mark.parametrize(
    ("wins", "expected"),
    [
        (82, "PERFECT SEASON. 82-0."),
        (81, "Better than the 73-9 Warriors, but not perfect."),
        (74, "Better than the 73-9 Warriors, but not perfect."),
        (73, "Tied the best record ever."),
        (72, "A contender, not a legend."),
        (60, "A contender, not a legend."),
        (59, "A playoff team."),
        (41, "A playoff team."),
        (40, "Lottery bound."),
        (0, "Lottery bound."),
    ],
)
def test_verdict(wins: int, expected: str) -> None:
    assert verdict(wins) == expected


def rating(**fields: float) -> TeamRating:
    values = {
        "net": 0.0,
        "pre_cap": 0.0,
        "talent": 0.0,
        "card_boost": 0.0,
        "talent_unshared": 0.0,
        "shot_sharing": 0.0,
        "under_usage": 0.0,
        "playmaking": 0.0,
        "rebounding": 0.0,
        "position_fit": 0.0,
        "usage_total": 100.0,
        "assist_total": 77.0,
        "rebound_total": 50.0,
    }
    return TeamRating.model_validate(values | fields)


class TestBreakdown:
    def test_ordinary_team_has_the_core_rows(self) -> None:
        rows = breakdown(rating(talent_unshared=5.0, talent=5.0, pre_cap=5.0, net=5.0))

        assert [label for label, _ in rows] == [
            "Talent",
            "Shot sharing",
            "Playmaking",
            "Rebounding",
            "Position fit",
        ]

    def test_optional_rows_appear_when_they_matter_and_everything_adds_up(self) -> None:
        r = rating(
            talent_unshared=34.0,
            card_boost=4.0,
            shot_sharing=-6.0,
            talent=28.0,
            under_usage=-1.0,
            playmaking=1.5,
            rebounding=2.0,
            position_fit=-0.5,
            pre_cap=30.0,
            net=23.5,
        )

        rows = dict(breakdown(r))

        assert rows["Talent"] == pytest.approx(30.0)
        assert rows["Special card"] == pytest.approx(4.0)
        assert rows["Shot creation"] == pytest.approx(-1.0)
        assert rows["Diminishing returns"] == pytest.approx(-6.5)
        assert sum(rows.values()) == pytest.approx(r.net)
