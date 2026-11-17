"""HTTP handlers: translate requests into game transitions and render the result.

Every action is a plain HTML form using post/redirect/get. Pages are rendered on the server,
so in Legend mode the stats never reach the browser before the lineup is locked.
"""

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from eighty_two_o.config import DEFAULT_DRAFT
from eighty_two_o.data.repository import Dataset
from eighty_two_o.draft import DraftError, rerolls_left, roster_view
from eighty_two_o.game import (
    Game,
    GameError,
    GameStore,
    Mode,
    Phase,
    apply_pick,
    apply_reroll,
    lock_lineup,
    new_game,
)
from eighty_two_o.rating import TeamRating

CREDIT = "Statistics from Basketball-Reference, via Sumitro Datta's CC0 dataset"

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["one"] = lambda value: f"{value:.1f}"
templates.env.filters["signed"] = lambda value: f"{value:+.1f}"
templates.env.filters["pct"] = lambda value: f"{100 * value:.1f}"
templates.env.globals["credit"] = CREDIT


def verdict(wins: int) -> str:
    """Describe a final record in one line.

    Args:
        wins: Games won out of 82.

    Returns:
        The verdict shown on the summary.
    """
    if wins >= 82:
        return "PERFECT SEASON. 82-0."
    if wins >= 74:
        return "Better than the 73-9 Warriors, but not perfect."
    if wins == 73:
        return "Tied the best record ever."
    if wins >= 60:
        return "A contender, not a legend."
    if wins >= 41:
        return "A playoff team."
    return "Lottery bound."


def breakdown(rating: TeamRating) -> list[tuple[str, float]]:
    """Explain a team rating as labelled parts that add up to the overall rating.

    Args:
        rating: The team's rating.

    Returns:
        ``(label, value)`` rows; rows that would read ``+0.0`` for every team (special card,
        shot creation, diminishing returns) are included only when they matter.
    """
    rows = [("Talent", rating.talent_unshared - rating.card_boost)]
    if abs(rating.card_boost) >= 0.05:
        rows.append(("Special card", rating.card_boost))
    rows.append(("Shot sharing", rating.shot_sharing))
    if abs(rating.under_usage) >= 0.05:
        rows.append(("Shot creation", rating.under_usage))
    rows += [
        ("Playmaking", rating.playmaking),
        ("Rebounding", rating.rebounding),
        ("Position fit", rating.position_fit),
    ]
    if abs(rating.net - rating.pre_cap) >= 0.05:
        rows.append(("Diminishing returns", rating.net - rating.pre_cap))
    return rows


def build_router(dataset: Dataset, store: GameStore) -> APIRouter:
    """Create the routes for one dataset and one game store.

    Args:
        dataset: The dataset to play with.
        store: Where games are kept between requests.

    Returns:
        The router to include in the app.
    """
    router = APIRouter()

    def page(
        request: Request, name: str, context: dict[str, Any], status_code: int = 200
    ) -> Response:
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    def back_to(game_id: str) -> Response:
        return RedirectResponse(f"/games/{game_id}", status_code=303)

    def not_found(request: Request) -> Response:
        return page(request, "not_found.html", {}, status_code=404)

    def render_game(
        request: Request, game: Game, error: str | None = None, status_code: int = 200
    ) -> Response:
        context: dict[str, Any] = {"game": game, "error": error}
        if game.phase is Phase.DRAFT:
            assert game.draft.current_roll is not None  # guaranteed by the draft phase
            entries = roster_view(game.draft, dataset)
            if game.mode is Mode.LEGEND:
                # Roster order is by minutes, which would give the stars away.
                entries = tuple(sorted(entries, key=lambda e: (e.card.name, e.card.card_id)))
            context |= {
                "team": dataset.team(game.draft.current_roll),
                "entries": entries,
                "pick_number": len(game.draft.picks),
                "rounds": DEFAULT_DRAFT.rounds,
                "rerolls_left": rerolls_left(game.draft),
            }
            return page(request, "draft.html", context, status_code)
        if game.phase is Phase.LINEUP:
            return page(request, "lineup.html", context, status_code)
        # The phase is DONE, so the season and rating exist.
        assert game.season is not None
        assert game.rating is not None
        context |= {
            "season": game.season,
            "rating": game.rating,
            "verdict": verdict(game.season.wins),
            "breakdown": breakdown(game.rating),
        }
        return page(request, "season.html", context, status_code)

    @router.get("/")
    def home(request: Request) -> Response:
        return page(request, "home.html", {"error": None})

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/games")
    def create_game(
        request: Request,
        mode: Annotated[str, Form()],
        seed: Annotated[str, Form()] = "",
    ) -> Response:
        try:
            chosen_mode = Mode(mode)
            chosen_seed = int(seed) if seed.strip() else None
        except ValueError:
            error = "Choose Rookie or Legend, and leave the seed empty or use a whole number."
            return page(request, "home.html", {"error": error}, status_code=400)
        game = new_game(dataset, chosen_mode, seed=chosen_seed)
        store.save(game)
        return back_to(game.id)

    @router.get("/games/{game_id}")
    def show_game(request: Request, game_id: str) -> Response:
        game = store.get(game_id)
        if game is None:
            return not_found(request)
        return render_game(request, game)

    @router.post("/games/{game_id}/pick")
    def pick_player(
        request: Request,
        game_id: str,
        card_id: Annotated[str, Form()],
        pick_number: Annotated[int, Form()],
    ) -> Response:
        game = store.get(game_id)
        if game is None:
            return not_found(request)
        if game.phase is not Phase.DRAFT or pick_number != len(game.draft.picks):
            return back_to(game_id)  # a stale form: double click or the back button
        try:
            game = apply_pick(game, dataset, card_id)
        except DraftError as error:
            return render_game(request, game, str(error), status_code=400)
        store.save(game)
        return back_to(game_id)

    @router.post("/games/{game_id}/reroll")
    def reroll_team(
        request: Request, game_id: str, pick_number: Annotated[int, Form()]
    ) -> Response:
        game = store.get(game_id)
        if game is None:
            return not_found(request)
        if game.phase is not Phase.DRAFT or pick_number != len(game.draft.picks):
            return back_to(game_id)
        try:
            game = apply_reroll(game, dataset)
        except DraftError as error:
            return render_game(request, game, str(error), status_code=400)
        store.save(game)
        return back_to(game_id)

    @router.post("/games/{game_id}/lineup")
    def set_lineup(
        request: Request,
        game_id: str,
        starters: Annotated[list[str] | None, Form()] = None,
    ) -> Response:
        game = store.get(game_id)
        if game is None:
            return not_found(request)
        if game.phase is not Phase.LINEUP:
            return back_to(game_id)
        try:
            game = lock_lineup(game, dataset, starters or [])
        except GameError as error:
            return render_game(request, game, str(error), status_code=400)
        store.save(game)
        return back_to(game_id)

    return router
