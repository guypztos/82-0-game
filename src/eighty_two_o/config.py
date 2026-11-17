"""Every tunable number in the game, grouped by the part of the game that uses it."""

from pydantic import BaseModel, ConfigDict


class DraftConfig(BaseModel):
    """Rules of the draft."""

    model_config = ConfigDict(frozen=True)

    rounds: int = 8
    """Players drafted: 5 starters and 3 bench players."""
    rerolls: int = 2
    """Rerolls available for the whole draft."""


DEFAULT_DRAFT = DraftConfig()
