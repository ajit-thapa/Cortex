"""Doorbell visitors and parcels, using a camera and the user's AI Task entity."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import Event
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import CONF_DOORBELL, CONF_DOORBELL_CAMERA
from .feature import Feature

KINDS = ("person", "delivery", "parcel", "animal", "vehicle", "nothing")
PROMPT = (
    "You are looking at a still image from a home security camera{where}. "
    "Reply in exactly this format: KIND: short description. "
    "KIND must be one of: person, delivery, parcel, animal, vehicle, nothing. "
    "Use delivery for a courier or postal worker, parcel when a package is visible "
    "and nobody is, nothing when the scene is empty. Keep the description under 20 words. "
    "Do not guess names."
)


def parse_look(text: str) -> tuple[str, str]:
    """Split a ``KIND: description`` reply. Unparseable replies count as a person."""
    head, _, rest = (text or "").strip().partition(":")
    kind = head.strip().lower()
    if kind in KINDS and rest.strip():
        return kind, rest.strip().rstrip(".")
    return "person", (text or "someone at the door").strip().rstrip(".")


class Visitors(Feature):
    name = "visitors"

    def __init__(self, brain) -> None:
        super().__init__(brain)
        self.log: list[dict[str, Any]] = []
        self.spots: dict[str, str] = {}
        self._last_ring: datetime | None = None

    def load(self, data) -> None:
        data = data or {}
        self.log = data.get("log", [])
        self.spots = data.get("spots", {})

    def dump(self) -> dict[str, Any]:
        return {"log": self.log[-100:], "spots": self.spots}

    async def start(self) -> None:
        ids = list(self.brain.opts.get(CONF_DOORBELL) or [])
        if ids:
            self._unsubs.append(async_track_state_change_event(self.hass, ids, self._ring))

    def set_spot(self, camera: str, spot: str) -> None:
        if spot:
            self.spots[camera] = spot
        else:
            self.spots.pop(camera, None)
        self.brain.save()

    @property
    def parcels_waiting(self) -> int:
        """Parcels seen in the last day and not yet marked collected."""
        cutoff = dt_util.now() - timedelta(hours=24)
        count = 0
        for item in reversed(self.log):
            when = dt_util.parse_datetime(item["time"])
            if when is None or when < cutoff or item["kind"] == "collected":
                break
            if item["kind"] == "parcel":
                count += 1
        return count

    def collected(self) -> None:
        self.log.append(
            {"time": dt_util.now().isoformat(timespec="seconds"), "kind": "collected", "text": "Parcels collected", "camera": None}
        )
        self.brain.save()

    def today_count(self) -> int:
        today = dt_util.now().date().isoformat()
        return sum(1 for v in self.log if v["time"].startswith(today) and v["kind"] != "nothing")

    async def _ring(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None or old is None or new.state == old.state:
            return
        # binary sensors ring on "on"; event entities change to a new timestamp
        domain = new.entity_id.split(".", 1)[0]
        if domain == "binary_sensor" and new.state != "on":
            return
        if new.state in ("unknown", "unavailable"):
            return
        now = dt_util.now()
        if self._last_ring and now - self._last_ring < timedelta(seconds=45):
            return
        self._last_ring = now
        await self.handle_visitor()

    async def handle_visitor(self, camera: str | None = None) -> dict[str, Any]:
        camera = camera or self.brain.opts.get(CONF_DOORBELL_CAMERA)
        kind, desc = "person", "someone is at the door"
        if camera:
            try:
                text = await self.brain.look(camera, None)
                kind, desc = parse_look(text)
            except HomeAssistantError:
                pass
        entry = {"time": dt_util.now().isoformat(timespec="seconds"), "kind": kind, "text": desc, "camera": camera}
        self.log.append(entry)
        self.brain.record("visitors")
        if kind == "parcel":
            self.brain.record("parcels")
        self.brain.log("visitor", f"{kind}: {desc}")
        self.brain.save()
        if kind == "nothing":
            return entry
        lead = {
            "delivery": "A delivery is at the door",
            "parcel": "A parcel has been left at the door",
            "animal": "An animal is at the door",
            "vehicle": "A vehicle is outside",
        }.get(kind, "Someone is at the door")
        await self.brain.speaker.say(f"{lead}: {desc}.", urgent=False, push=True)
        return entry
