import pytest

from eighty_two_o.data.repository import Dataset
from eighty_two_o.draft import DraftError, roster_view
from eighty_two_o.game import (
    Game,
    GameError,
    GameStore,
    InMemoryGameStore,
    Mode,
    Phase,
    apply_pick,
    apply_reroll,
    lock_lineup,
    new_game,
)


def draft_everything(game: Game, dataset: Dataset, reroll_first: bool = False) -> Game:
    if reroll_first:
        game = apply_reroll(game, dataset)
    while game.phase is Phase.DRAFT:
        card_id = next(e.card.card_id for e in roster_view(game.draft, dataset) if e.available)
        game = apply_pick(game, dataset, card_id)
    return game


def first_five(game: Game) -> list[str]:
    return [card.card_id for card in game.draft.picks[:5]]


def play(dataset: Dataset, seed: int, mode: Mode = Mode.ROOKIE) -> Game:
    game = draft_everything(new_game(dataset, mode, seed=seed), dataset, reroll_first=True)
    return lock_lineup(game, dataset, first_five(game))


@pytest.fixture(scope="module")
def finished(dataset: Dataset) -> Game:
    return play(dataset, seed=42)


class TestNewGame:
    def test_starts_in_the_draft_with_a_roll(self, dataset: Dataset) -> None:
        game = new_game(dataset, Mode.LEGEND, seed=5)

        assert game.phase is Phase.DRAFT
        assert game.seed == 5
        assert game.mode is Mode.LEGEND
        assert game.draft.current_roll is not None
        assert game.rating is None
        assert game.season is None

    def test_random_seed_and_id_when_not_given(self, dataset: Dataset) -> None:
        first = new_game(dataset, Mode.ROOKIE)
        second = new_game(dataset, Mode.ROOKIE)

        assert first.id != second.id
        assert first.seed != second.seed


class TestFullGame:
    def test_finished_game(self, finished: Game) -> None:
        assert finished.phase is Phase.DONE
        assert finished.rating is not None
        assert finished.season is not None
        assert len(finished.season.games) == 82
        assert len(finished.starters) == 5
        assert len(finished.bench) == 3

    def test_same_seed_and_choices_replay_the_same_game(
        self, dataset: Dataset, finished: Game
    ) -> None:
        replay = play(dataset, seed=42)

        assert replay.season == finished.season
        assert replay.rating == finished.rating
        assert replay.draft == finished.draft

    def test_starters_and_bench_keep_draft_order(self, dataset: Dataset) -> None:
        game = draft_everything(new_game(dataset, Mode.ROOKIE, seed=8), dataset)
        picks = [card.card_id for card in game.draft.picks]

        done = lock_lineup(game, dataset, list(reversed(picks[3:])))

        assert [c.card_id for c in done.starters] == picks[3:]
        assert [c.card_id for c in done.bench] == picks[:3]


class TestStatsVisibility:
    def test_rookie_always_sees_stats(self, dataset: Dataset) -> None:
        assert new_game(dataset, Mode.ROOKIE, seed=1).stats_visible

    def test_legend_sees_stats_only_when_done(self, dataset: Dataset) -> None:
        game = new_game(dataset, Mode.LEGEND, seed=1)
        assert not game.stats_visible

        game = draft_everything(game, dataset)
        assert game.phase is Phase.LINEUP
        assert not game.stats_visible

        assert lock_lineup(game, dataset, first_five(game)).stats_visible


class TestInvalidTransitions:
    def test_cannot_pick_or_reroll_after_the_draft(self, dataset: Dataset) -> None:
        game = draft_everything(new_game(dataset, Mode.ROOKIE, seed=3), dataset)

        with pytest.raises(GameError, match="draft is already over"):
            apply_pick(game, dataset, game.draft.picks[0].card_id)
        with pytest.raises(GameError, match="draft is already over"):
            apply_reroll(game, dataset)

    def test_cannot_lock_a_lineup_during_the_draft(self, dataset: Dataset) -> None:
        game = new_game(dataset, Mode.ROOKIE, seed=3)

        with pytest.raises(GameError, match="only set the lineup"):
            lock_lineup(game, dataset, [])

    def test_cannot_lock_a_lineup_twice(self, dataset: Dataset, finished: Game) -> None:
        with pytest.raises(GameError, match="only set the lineup"):
            lock_lineup(finished, dataset, first_five(finished))

    def test_draft_errors_pass_through(self, dataset: Dataset) -> None:
        game = new_game(dataset, Mode.ROOKIE, seed=3)

        with pytest.raises(DraftError):
            apply_pick(game, dataset, "nobody:2016:TST")


@pytest.fixture(scope="module")
def drafted(dataset: Dataset) -> Game:
    return draft_everything(new_game(dataset, Mode.ROOKIE, seed=6), dataset)


class TestLineupValidation:
    @pytest.mark.parametrize("count", [4, 6])
    def test_exactly_five_starters(self, dataset: Dataset, drafted: Game, count: int) -> None:
        ids = [card.card_id for card in drafted.draft.picks[:count]]

        with pytest.raises(GameError, match="exactly 5 starters"):
            lock_lineup(drafted, dataset, ids)

    def test_duplicates_are_rejected(self, dataset: Dataset, drafted: Game) -> None:
        ids = first_five(drafted)
        ids[4] = ids[0]

        with pytest.raises(GameError, match="only be chosen once"):
            lock_lineup(drafted, dataset, ids)

    def test_undrafted_card_is_rejected(self, dataset: Dataset, drafted: Game) -> None:
        ids = first_five(drafted)
        drafted_ids = {card.card_id for card in drafted.draft.picks}
        ids[4] = next(p.card_id for p in dataset.players if p.card_id not in drafted_ids)

        with pytest.raises(GameError, match="from your drafted players"):
            lock_lineup(drafted, dataset, ids)


class TestStore:
    def test_save_and_get(self, finished: Game) -> None:
        store = InMemoryGameStore()

        store.save(finished)

        assert store.get(finished.id) == finished
        assert store.get("missing") is None

    def test_saving_again_replaces_the_game(self, dataset: Dataset) -> None:
        store = InMemoryGameStore()
        game = new_game(dataset, Mode.ROOKIE, seed=1)
        store.save(game)

        updated = apply_reroll(game, dataset)
        store.save(updated)

        assert store.get(game.id) == updated
        assert len(store) == 1

    def test_oldest_saved_game_is_evicted(self, dataset: Dataset) -> None:
        store = InMemoryGameStore(max_games=2)
        games = [new_game(dataset, Mode.ROOKIE, seed=i) for i in range(3)]
        store.save(games[0])
        store.save(games[1])
        store.save(games[0])  # touching game 0 makes game 1 the oldest

        store.save(games[2])

        assert store.get(games[1].id) is None
        assert store.get(games[0].id) == games[0]
        assert store.get(games[2].id) == games[2]
        assert len(store) == 2

    def test_satisfies_the_protocol(self) -> None:
        store: GameStore = InMemoryGameStore()

        assert store.get("anything") is None


@pytest.mark.parametrize("phase", list(Phase))
def test_game_round_trips_through_json(dataset: Dataset, phase: Phase) -> None:
    game = new_game(dataset, Mode.LEGEND, seed=12)
    if phase is not Phase.DRAFT:
        game = draft_everything(game, dataset)
    if phase is Phase.DONE:
        game = lock_lineup(game, dataset, first_five(game))
    assert game.phase is phase

    assert Game.model_validate_json(game.model_dump_json()) == game
