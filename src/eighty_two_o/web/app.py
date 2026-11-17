"""The FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from eighty_two_o.data.repository import Dataset, load_dataset
from eighty_two_o.game import GameStore, InMemoryGameStore
from eighty_two_o.store import InMemoryStore, Store
from eighty_two_o.sweep.game import SweepGame
from eighty_two_o.sweep.repository import SweepDataset, load_sweep_dataset
from eighty_two_o.web.routes import build_router
from eighty_two_o.web.sweep_routes import build_sweep_router

WEB_DIR = Path(__file__).parent


def create_app(
    dataset: Dataset | None = None,
    store: GameStore | None = None,
    sweep_dataset: SweepDataset | None = None,
    sweep_store: Store[SweepGame] | None = None,
) -> FastAPI:
    """Build the web app with both games.

    Args:
        dataset: The basketball dataset; the bundled one when omitted.
        store: Where basketball games are kept; a new in-memory store when omitted.
        sweep_dataset: The Clean Sweep dataset; the bundled one when omitted.
        sweep_store: Where Clean Sweep games are kept; a new in-memory store when omitted.

    Returns:
        The application, ready for ``uvicorn``.
    """
    app = FastAPI(title="82-0", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(
        build_router(
            load_dataset() if dataset is None else dataset,
            InMemoryGameStore() if store is None else store,
        )
    )
    app.include_router(
        build_sweep_router(
            load_sweep_dataset() if sweep_dataset is None else sweep_dataset,
            InMemoryStore[SweepGame]() if sweep_store is None else sweep_store,
        )
    )
    return app
