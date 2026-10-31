"""Base class for Cortex features."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .runtime import Cortex


class Feature:
    """A self-contained capability with its own persisted state and listeners."""

    name = ""

    def __init__(self, brain: Cortex) -> None:
        self.brain = brain
        self.hass: HomeAssistant = brain.hass
        self._unsubs: list[Callable[[], None]] = []

    # persistence -----------------------------------------------------------
    def load(self, data: dict[str, Any] | None) -> None:
        """Restore state saved by ``dump``."""

    def dump(self) -> dict[str, Any]:
        return {}

    # lifecycle -------------------------------------------------------------
    async def start(self) -> None:
        """Begin listening. Called once after ``load``."""

    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    def clear_listeners(self) -> None:
        self.stop()
