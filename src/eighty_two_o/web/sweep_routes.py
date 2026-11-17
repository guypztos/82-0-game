"""HTTP handlers for Clean Sweep, the motor-racing game.

The same shape as ``routes.py``: plain HTML forms with post/redirect/get, rendered on the
server, so in Legend mode no rating or result reaches the browser before the reserve is chosen.
"""

from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from eighty_two_o.config import DEFAULT_SWEEP_SIM
from eighty_two_o.game import GameError, Mode, Phase
from eighty_two_o.store import Store
from eighty_two_o.sweep.draft import ROUNDS, SweepDraftError, board, rerolls_left
from eighty_two_o.sweep.game import SweepGame, apply_pick, apply_reroll, lock_lineup, new_game
from eighty_two_o.sweep.models import PART_SLOTS, CarSeason, DriverSeason, Slot
from eighty_two_o.sweep.repository import SweepDataset
from eighty_two_o.sweep.season import CarResult, SweepSeason
from eighty_two_o.sweep.team import (
    Team,
    car_strength,
    display_rating,
    part_value,
    retirement_chances,
)
from eighty_two_o.web.livery import engine_colour, livery, part_colour
from eighty_two_o.web.routes import templates

SWEEP_CREDIT = (
    "Race results from F1DB (CC BY 4.0), turned into ratings by this game. "
    "Unofficial: not associated with the Formula 1 companies."
)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def sweep_verdict(wins: int, races: int) -> str:
    """Describe a final record in one line.

    Args:
        wins: Races won.
        races: Races in the season.

    Returns:
        The verdict shown on the summary.
    """
    if wins >= races:
        return f"CLEAN SWEEP. {races} wins from {races}."
    if wins == races - 1:
        return "One race short of perfect."
    if wins >= 0.75 * races:
        return "A dominant champion, but not a clean sweep."
    if wins >= 0.5 * races:
        return "A title contender."
    if wins >= 0.2 * races:
        return "A race winner."
    if wins >= 1:
        return "A few good Sundays."
    return "Winless."


def part_name(slot: Slot, car: CarSeason) -> str:
    """Name a part by where it came from, e.g. ``"2014 Mercedes"`` for an engine.

    Args:
        slot: One of ``PART_SLOTS``.
        car: The car the part comes from.

    Returns:
        The name shown on the board and in the team.
    """
    if slot is Slot.ENGINE:
        return f"{car.year} {car.engine_name}"
    if slot is Slot.PIT_CREW:
        return car.label
    return f"{car.label} {car.chassis_name}"


def part_line(slot: Slot, car: CarSeason) -> str:
    """The real-world numbers behind a part, shown in Rookie mode.

    Args:
        slot: One of ``PART_SLOTS``.
        car: The car the part comes from.

    Returns:
        A short stat line.
    """
    if slot is Slot.ENGINE:
        line = f"{_count(car.engine_wins, 'win')} across {_count(car.engine_teams, 'team')}"
        if car.engine_badge != car.engine_name:
            line += f", badged {car.engine_badge}"
        return line
    if slot is Slot.CHASSIS:
        return (
            f"{_count(car.wins, 'win')}, {_count(car.poles, 'pole')},"
            f" {_count(car.podiums, 'podium')} in {_count(car.races, 'race')}"
        )
    if slot is Slot.RELIABILITY:
        retirements = _count(car.mechanical_retirements, "mechanical retirement")
        return f"{retirements} in {_count(car.starts, 'start')}"
    if car.pit_rank is None:
        return "No pit-stop timing before 1994: rated average"
    return f"{_ordinal(car.pit_rank)} fastest pit stops that season"


def driver_line(driver: DriverSeason) -> str:
    """The real-world numbers behind a driver card, shown in Rookie mode.

    Args:
        driver: The card.

    Returns:
        A short stat line.
    """
    return (
        f"{_count(driver.starts, 'start')}, {_count(driver.wins, 'win')},"
        f" {_count(driver.podiums, 'podium')}, {_count(driver.poles, 'pole')}"
    )


def part_rating(slot: Slot, car: CarSeason) -> int:
    """The 1 to 99 rating of a part.

    Args:
        slot: One of ``PART_SLOTS``.
        car: The car the part comes from.

    Returns:
        The rating.
    """
    return display_rating(slot, part_value(slot, car))


def driver_rating(driver: DriverSeason) -> int:
    """The 1 to 99 rating of a driver card.

    Args:
        driver: The card.

    Returns:
        The rating.
    """
    return display_rating(Slot.DRIVER, driver.rating)


def car_result_line(result: CarResult) -> str:
    """How one of the player's cars did, e.g. ``"P1 Max Verstappen"``.

    Args:
        result: The car's result.

    Returns:
        The text shown on the results list.
    """
    name = f"{result.driver} (reserve)" if result.reserve else result.driver
    if result.position is None:
        return f"{name} out ({result.retirement})"
    return f"P{result.position} {name}"


def beaten_by(season: SweepSeason) -> list[tuple[str, int]]:
    """Who won the races the player lost, most frequent first.

    Args:
        season: The season.

    Returns:
        ``(winner and car, races)`` pairs; races nobody finished count as "Nobody finished".
    """
    winners = Counter(
        "Nobody finished" if race.winner is None else f"{race.winner}, {race.winner_car}"
        for race in season.beaten_by
    )
    return winners.most_common()


def car_breakdown(team: Team) -> list[tuple[str, float]]:
    """Explain the car's strength as the three parts that add up to it.

    Args:
        team: The team.

    Returns:
        ``(label, value)`` rows for the engine, chassis and pit crew.
    """
    return [
        ("Engine", team.engine.engine),
        ("Chassis", team.chassis.chassis),
        ("Pit crew", team.pit_crew.pit),
    ]


templates.env.globals |= {
    "sweep_credit": SWEEP_CREDIT,
    "part_name": part_name,
    "part_line": part_line,
    "driver_line": driver_line,
    "part_rating": part_rating,
    "driver_rating": driver_rating,
    "part_value": part_value,
    "car_result_line": car_result_line,
    "part_slots": PART_SLOTS,
    "livery": livery,
    "engine_colour": engine_colour,
    "part_colour": part_colour,
}
templates.env.filters["signed2"] = lambda value: f"{value:+.2f}"
templates.env.filters["ordinal"] = _ordinal


def build_sweep_router(dataset: SweepDataset, store: Store[SweepGame]) -> APIRouter:
    """Create the Clean Sweep routes for one dataset and one game store.

    Args:
        dataset: The dataset to play with.
        store: Where games are kept between requests.

    Returns:
        The router to include in the app.
    """
    router = APIRouter(prefix="/sweep")
    strongest = max(dataset.cars, key=lambda car: car.car)

    def page(
        request: Request, name: str, context: dict[str, Any], status_code: int = 200
    ) -> Response:
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    def back_to(game_id: str) -> Response:
        return RedirectResponse(f"/sweep/games/{game_id}", status_code=303)

    def not_found(request: Request) -> Response:
        return page(request, "not_found.html", {}, status_code=404)

    def render_game(
        request: Request, game: SweepGame, error: str | None = None, status_code: int = 200
    ) -> Response:
        context: dict[str, Any] = {"game": game, "error": error, "car_of": dataset.car}
        if game.phase is Phase.DRAFT:
            b = board(game.draft, dataset)
            drivers = b.drivers
            if game.mode is Mode.LEGEND:
                # Roster order is by starts, which would hint at who the stars are.
                drivers = tuple(sorted(drivers, key=lambda o: (o.card.name, o.card.card_id)))
            context |= {
                "board": b,
                "drivers": drivers,
                "pick_number": game.draft.picks_made,
                "rounds": ROUNDS,
                "rerolls_left": rerolls_left(game.draft),
            }
            return page(request, "sweep/draft.html", context, status_code)
        if game.phase is Phase.LINEUP:
            return page(request, "sweep/lineup.html", context, status_code)
        # The phase is DONE, so the team and season exist.
        assert game.team is not None
        assert game.season is not None
        mechanical, _ = retirement_chances(game.team.reliability.reliability, 0.0)
        context |= {
            "team": game.team,
            "season": game.season,
            "verdict": sweep_verdict(game.season.wins, len(game.season.races)),
            "beaten_by": beaten_by(game.season),
            "breakdown": car_breakdown(game.team),
            "strength": car_strength(game.team),
            "strongest": strongest,
            "mechanical": mechanical,
            "sim": DEFAULT_SWEEP_SIM,
        }
        return page(request, "sweep/season.html", context, status_code)

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
    def take_item(
        request: Request,
        game_id: str,
        item: Annotated[str, Form()],
        pick_number: Annotated[int, Form()],
    ) -> Response:
        game = store.get(game_id)
        if game is None:
            return not_found(request)
        if game.phase is not Phase.DRAFT or pick_number != game.draft.picks_made:
            return back_to(game_id)  # a stale form: double click or the back button
        try:
            game = apply_pick(game, dataset, item)
        except SweepDraftError as error:
            return render_game(request, game, str(error), status_code=400)
        store.save(game)
        return back_to(game_id)

    @router.post("/games/{game_id}/reroll")
    def reroll_car(request: Request, game_id: str, pick_number: Annotated[int, Form()]) -> Response:
        game = store.get(game_id)
        if game is None:
            return not_found(request)
        if game.phase is not Phase.DRAFT or pick_number != game.draft.picks_made:
            return back_to(game_id)
        try:
            game = apply_reroll(game, dataset)
        except SweepDraftError as error:
            return render_game(request, game, str(error), status_code=400)
        store.save(game)
        return back_to(game_id)

    @router.post("/games/{game_id}/lineup")
    def choose_reserve(
        request: Request, game_id: str, reserve: Annotated[str, Form()] = ""
    ) -> Response:
        game = store.get(game_id)
        if game is None:
            return not_found(request)
        if game.phase is not Phase.LINEUP:
            return back_to(game_id)
        try:
            game = lock_lineup(game, dataset, reserve)
        except GameError as error:
            return render_game(request, game, str(error), status_code=400)
        store.save(game)
        return back_to(game_id)

    return router
