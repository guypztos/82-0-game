"""Command-line entry point: start the game server and open it in the browser."""

import os
import webbrowser
from threading import Timer

import uvicorn

BROWSER_DELAY_SECONDS = 1.0
ALL_INTERFACES = {"0.0.0.0", "::"}


def main() -> None:
    """Run the game.

    The server listens on ``HOST`` and ``PORT`` from the environment (default
    ``127.0.0.1:8000``). The browser opens shortly after, once the server is up.
    """
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    browser_host = "127.0.0.1" if host in ALL_INTERFACES else host
    url = f"http://{browser_host}:{port}/"

    print(f"82-0 is running at {url} (press Ctrl+C to stop)")
    Timer(BROWSER_DELAY_SECONDS, webbrowser.open, args=(url,)).start()
    uvicorn.run("eighty_two_o.web.app:create_app", factory=True, host=host, port=port)
