"""The FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from eighty_two_o.data.repository import Dataset, load_dataset
from eighty_two_o.game import GameStore, InMemoryGameStore
from eighty_two_o.web.routes import build_router

WEB_DIR = Path(__file__).parent


def create_app(dataset: Dataset | None = None, store: GameStore | None = None) -> FastAPI:
    """Build the web app.

    Args:
        dataset: The dataset to play with; the bundled one when omitted.
        store: Where games are kept; a new in-memory store when omitted.

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
    return app
