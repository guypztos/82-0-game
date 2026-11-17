"""Team and engine colours for drawing the player's Clean Sweep car.

Plain colours only, as a fact about how each team's cars looked; no logos or sponsor marks.
A team that changed its look has one entry per era, keyed by the first year of that era.
"""

from typing import NamedTuple

from eighty_two_o.sweep.models import CarSeason, Slot


class Livery(NamedTuple):
    """A main colour and an accent colour, as CSS hex strings."""

    primary: str
    accent: str


NEUTRAL = Livery("#9aa3ad", "#4a525c")
"""For any team without a listed colour."""

TEAM_LIVERIES: dict[str, tuple[tuple[int, Livery], ...]] = {
    "alphatauri": ((0, Livery("#e8ebf0", "#1b2a4a")),),
    "alpine": ((0, Livery("#1f5fd6", "#f27fb4")),),
    "benetton": ((0, Livery("#2fa05a", "#2a73c9")),),
    "bmw-sauber": ((0, Livery("#f2f4f7", "#1e5bb8")),),
    "brabham": ((0, Livery("#1d3f8f", "#f2f4f7")),),
    "brawn": ((0, Livery("#f2f4f7", "#d6f53b")),),
    "ferrari": ((0, Livery("#d40d12", "#f2c200")),),
    "honda": ((0, Livery("#f2f4f7", "#c8102e")),),
    "jordan": ((0, Livery("#f5d000", "#1b1b1b")),),
    "ligier": ((0, Livery("#2a63c9", "#f2f4f7")),),
    "lotus": ((0, Livery("#141414", "#c9a227")), (1987, Livery("#f5d000", "#1a4fa0"))),
    "lotus-f1": ((0, Livery("#141414", "#c9a227")),),
    "mclaren": (
        (0, Livery("#f2f4f7", "#d2232a")),
        (1997, Livery("#a7adb5", "#1b1b1b")),
        (2015, Livery("#2b2d31", "#9aa3ad")),
        (2017, Livery("#ff8000", "#1f6fd1")),
    ),
    "mercedes": ((0, Livery("#c0c6cc", "#00a19c")),),
    "racing-point": ((0, Livery("#f596c8", "#1f5fa8")),),
    "red-bull": ((0, Livery("#1e2a5a", "#d71a28")),),
    "renault": ((0, Livery("#f5d000", "#1b1b1b")), (2005, Livery("#1f4fa0", "#f5d000"))),
    "stewart": ((0, Livery("#f2f4f7", "#1b1b1b")),),
    "toro-rosso": ((0, Livery("#1e2a5a", "#c0c6cc")),),
    "tyrrell": ((0, Livery("#1d2e6b", "#f2f4f7")),),
    "williams": ((0, Livery("#f2f4f7", "#1d4f9c")), (1990, Livery("#1d4f9c", "#f2f4f7"))),
}

ENGINE_COLOURS: dict[str, str] = {
    "bmw": "#1e5bb8",
    "ferrari": "#d40d12",
    "ford": "#1f3f8f",
    "honda": "#e6e9ee",
    "matra": "#2a63c9",
    "mercedes": "#00a19c",
    "mugen-honda": "#c8102e",
    "renault": "#f5d000",
    "tag": "#8a8f96",
}


def livery(car: CarSeason) -> Livery:
    """The colours of a team-season.

    Args:
        car: The team-season.

    Returns:
        Its colours, or ``NEUTRAL`` for a team without a listed colour.
    """
    eras = TEAM_LIVERIES.get(car.constructor_id)
    if eras is None:
        return NEUTRAL
    return next(colours for start, colours in reversed(eras) if car.year >= start)


def engine_colour(car: CarSeason) -> str:
    """The colour of an engine maker, falling back to the team's main colour.

    Args:
        car: The team-season the engine comes from.

    Returns:
        A CSS hex colour.
    """
    return ENGINE_COLOURS.get(car.engine_id, livery(car).primary)


def part_colour(slot: Slot, car: CarSeason) -> str:
    """The colour a part is drawn in: the engine maker's for an engine, else the team's.

    Args:
        slot: One of ``PART_SLOTS``.
        car: The team-season the part comes from.

    Returns:
        A CSS hex colour.
    """
    return engine_colour(car) if slot is Slot.ENGINE else livery(car).primary
