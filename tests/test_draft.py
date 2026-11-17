import pytest

from eighty_two_o.config import DraftConfig
from eighty_two_o.data.repository import Dataset
from eighty_two_o.draft import (
    DraftError,
    DraftState,
    pick,
    reroll,
    rerolls_left,
    roster_view,
    start_draft,
)
from tests.factories import make_dataset, make_player, make_team


@pytest.fixture
def small() -> Dataset:
    return make_dataset()


def first_available(state: DraftState, dataset: Dataset) -> str:
    return next(entry.card.card_id for entry in roster_view(state, dataset) if entry.available)


def full_draft(dataset: Dataset, seed: int, rerolls_at: tuple[int, ...] = ()) -> DraftState:
    """Draft the first available player every round, rerolling before the given picks."""
    state = start_draft(dataset, seed)
    while not state.complete:
        if len(state.picks) in rerolls_at and rerolls_left(state) > 0:
            state = reroll(state, dataset)
            rerolls_at = tuple(i for i in rerolls_at if i != len(state.picks))
            continue
        state = pick(state, dataset, first_available(state, dataset))
    return state


class TestStart:
    def test_first_roll_is_a_real_team_season(self, small: Dataset) -> None:
        state = start_draft(small, seed=1)

        assert state.current_roll in {team.key for team in small.team_seasons}
        assert state.rolled == (state.current_roll,)
        assert state.picks == ()
        assert state.rerolls_used == 0
        assert not state.complete

    def test_same_seed_gives_the_same_draft(self, small: Dataset) -> None:
        assert full_draft(small, seed=7, rerolls_at=(2,)) == full_draft(
            small, seed=7, rerolls_at=(2,)
        )

    def test_different_seeds_give_different_drafts(self, small: Dataset) -> None:
        rolls = {full_draft(small, seed=seed).rolled for seed in range(10)}

        assert len(rolls) > 1


class TestReroll:
    def test_reroll_replaces_the_roll_and_spends_a_reroll(self, small: Dataset) -> None:
        state = start_draft(small, seed=3)

        after = reroll(state, small)

        assert after.current_roll != state.current_roll
        assert after.rolled == (*state.rolled, after.current_roll)
        assert after.rerolls_used == 1
        assert rerolls_left(after) == 1

    def test_rerolls_run_out(self, small: Dataset) -> None:
        state = reroll(reroll(start_draft(small, seed=3), small), small)

        assert rerolls_left(state) == 0
        with pytest.raises(DraftError, match="no rerolls left"):
            reroll(state, small)

    def test_reroll_limit_comes_from_the_config(self, small: Dataset) -> None:
        state = start_draft(small, seed=3)

        with pytest.raises(DraftError, match="no rerolls left"):
            reroll(state, small, DraftConfig(rerolls=0))

    def test_cannot_reroll_a_finished_draft(self, small: Dataset) -> None:
        with pytest.raises(DraftError, match="already over"):
            reroll(full_draft(small, seed=5), small)

    def test_runs_out_of_team_seasons(self) -> None:
        dataset = Dataset([make_player()], [make_team()])
        state = start_draft(dataset, seed=1)

        with pytest.raises(DraftError, match="no team-seasons left"):
            reroll(state, dataset)


class TestPick:
    def test_pick_adds_the_card_and_rolls_again(self, small: Dataset) -> None:
        state = start_draft(small, seed=2)
        card_id = first_available(state, small)

        after = pick(state, small, card_id)

        assert [card.card_id for card in after.picks] == [card_id]
        assert after.current_roll is not None
        assert after.current_roll not in state.rolled
        assert after.rolled == (*state.rolled, after.current_roll)

    def test_draft_completes_after_eight_picks(self, small: Dataset) -> None:
        state = full_draft(small, seed=4)

        assert state.complete
        assert len(state.picks) == 8
        assert state.current_roll is None
        assert roster_view(state, small) == ()

    def test_rounds_come_from_the_config(self, small: Dataset) -> None:
        config = DraftConfig(rounds=1)
        state = start_draft(small, seed=4, config=config)

        after = pick(state, small, first_available(state, small), config)

        assert after.complete

    def test_team_seasons_never_repeat(self, small: Dataset) -> None:
        for seed in range(20):
            state = full_draft(small, seed=seed, rerolls_at=(0, 5))

            assert len(set(state.rolled)) == len(state.rolled) == 10

    def test_card_not_on_the_roster_is_rejected(self, small: Dataset) -> None:
        state = start_draft(small, seed=2)
        elsewhere = next(
            card
            for team in small.team_seasons
            if team.key != state.current_roll
            for card in small.roster(team.key)
        )

        with pytest.raises(DraftError, match="not on this roster"):
            pick(state, small, elsewhere.card_id)

    def test_unknown_card_is_rejected(self, small: Dataset) -> None:
        with pytest.raises(DraftError, match="not on this roster"):
            pick(start_draft(small, seed=2), small, "nobody:2016:TST")

    def test_cannot_pick_in_a_finished_draft(self, small: Dataset) -> None:
        state = full_draft(small, seed=5)

        with pytest.raises(DraftError, match="already over"):
            pick(state, small, state.picks[0].card_id)


class TestOnePersonPerDraft:
    """``make_dataset`` puts the last player of team 1 on team 0's 2015 roster too."""

    @pytest.fixture
    def state(self, small: Dataset) -> DraftState:
        drafted = small.card("p0109:2016:T01")
        return DraftState(seed=1, picks=(drafted,), current_roll="T00:2015", rolled=("T01:2016",))

    def test_other_season_of_a_drafted_person_is_unavailable(
        self, state: DraftState, small: Dataset
    ) -> None:
        availability = {entry.card.card_id: entry.available for entry in roster_view(state, small)}

        assert availability["p0109:2015:T00"] is False
        assert availability["p0209:2015:T00"] is True

    def test_drafting_the_same_person_again_is_rejected(
        self, state: DraftState, small: Dataset
    ) -> None:
        with pytest.raises(DraftError, match="already drafted Player 1-9"):
            pick(state, small, "p0109:2015:T00")


def test_roster_view_is_in_roster_order(small: Dataset) -> None:
    state = start_draft(small, seed=9)
    assert state.current_roll is not None

    cards = tuple(entry.card for entry in roster_view(state, small))

    assert cards == small.roster(state.current_roll)


def test_state_round_trips_through_json(small: Dataset) -> None:
    state = full_draft(small, seed=11, rerolls_at=(3,))

    assert DraftState.model_validate_json(state.model_dump_json()) == state


def test_real_drafts_always_have_a_legal_pick(dataset: Dataset) -> None:
    for seed in range(50):
        state = full_draft(dataset, seed=seed, rerolls_at=(1, 4))

        assert len({card.player_id for card in state.picks}) == 8
