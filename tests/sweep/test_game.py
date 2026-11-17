import pytest

from eighty_two_o.game import GameError, Mode, Phase
from eighty_two_o.sweep.draft import board
from eighty_two_o.sweep.game import (
    SweepGame,
    apply_pick,
    apply_reroll,
    lock_lineup,
    new_game,
)
from eighty_two_o.sweep.repository import SweepDataset


def first_legal(game: SweepGame, dataset: SweepDataset) -> str:
    b = board(game.draft, dataset)
    part = next((o.slot.value for o in b.parts if o.available), None)
    if part is not None:
        return part
    return f"driver:{next(o.card.card_id for o in b.drivers if o.available)}"


def drafted(dataset: SweepDataset, mode: Mode = Mode.ROOKIE, seed: int = 42) -> SweepGame:
    game = new_game(dataset, mode, seed=seed)
    while game.phase is Phase.DRAFT:
        game = apply_pick(game, dataset, first_legal(game, dataset))
    return game


def test_new_game(sweep_dataset: SweepDataset) -> None:
    game = new_game(sweep_dataset, Mode.LEGEND, seed=9)

    assert game.phase is Phase.DRAFT
    assert not game.stats_visible
    assert game.draft.current_roll is not None
    assert new_game(sweep_dataset, Mode.ROOKIE).id != game.id
    assert new_game(sweep_dataset, Mode.ROOKIE).stats_visible


def test_whole_game_is_deterministic(sweep_dataset: SweepDataset) -> None:
    def play() -> SweepGame:
        game = drafted(sweep_dataset, Mode.LEGEND)
        assert game.phase is Phase.LINEUP
        assert not game.stats_visible
        return lock_lineup(game, sweep_dataset, game.draft.drivers[0].card_id)

    first, second = play(), play()

    assert first.phase is Phase.DONE
    assert first.stats_visible
    assert first.season == second.season
    assert first.team == second.team
    assert first.team is not None
    assert first.team.reserve == first.draft.drivers[0]
    assert first.team.mains == first.draft.drivers[1:]


def test_invalid_transitions(sweep_dataset: SweepDataset) -> None:
    draft_phase = new_game(sweep_dataset, Mode.ROOKIE, seed=1)
    lineup = drafted(sweep_dataset)
    done = lock_lineup(lineup, sweep_dataset, lineup.draft.drivers[2].card_id)

    with pytest.raises(GameError, match="only choose the reserve"):
        lock_lineup(draft_phase, sweep_dataset, "anything")
    for game in (lineup, done):
        with pytest.raises(GameError, match="already over"):
            apply_pick(game, sweep_dataset, "engine")
        with pytest.raises(GameError, match="already over"):
            apply_reroll(game, sweep_dataset)
    with pytest.raises(GameError, match="only choose the reserve"):
        lock_lineup(done, sweep_dataset, done.draft.drivers[0].card_id)


def test_reserve_must_be_drafted(sweep_dataset: SweepDataset) -> None:
    with pytest.raises(GameError, match="one of your three drivers"):
        lock_lineup(drafted(sweep_dataset), sweep_dataset, "max-verstappen:2025:red-bull:x")


def test_reroll(sweep_dataset: SweepDataset) -> None:
    game = new_game(sweep_dataset, Mode.ROOKIE, seed=3)

    assert apply_reroll(game, sweep_dataset).draft.current_roll != game.draft.current_roll


def test_round_trip_in_every_phase(sweep_dataset: SweepDataset) -> None:
    lineup = drafted(sweep_dataset)
    done = lock_lineup(lineup, sweep_dataset, lineup.draft.drivers[1].card_id)

    for game in (new_game(sweep_dataset, Mode.ROOKIE, seed=5), lineup, done):
        assert SweepGame.model_validate_json(game.model_dump_json()) == game
