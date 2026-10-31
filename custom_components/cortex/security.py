"""Night watch for doors and windows, and a read-only security check."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import Event
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from datetime import timedelta

from .const import CONF_NIGHT_END, CONF_NIGHT_START, CONF_NIGHT_WATCH
from .feature import Feature
from .gate import in_quiet_hours, parse_time

OPENING_CLASSES = {"door", "window", "garage_door", "opening"}
COVER_CLASSES = {"garage", "gate", "door"}
COOLDOWN = timedelta(minutes=5)


def friendly(state) -> str:
    return state.attributes.get("friendly_name", state.entity_id)


class Security(Feature):
    name = "security"

    def __init__(self, brain) -> None:
        super().__init__(brain)
        self._last: dict[str, datetime] = {}

    def openings(self) -> list[str]:
        return [
            s.entity_id
            for s in self.hass.states.async_all("binary_sensor")
            if s.attributes.get("device_class") in OPENING_CLASSES
        ]

    def is_night(self, now: datetime | None = None) -> bool:
        o = self.brain.opts
        return in_quiet_hours(
            now or dt_util.now(),
            parse_time(str(o[CONF_NIGHT_START])),
            parse_time(str(o[CONF_NIGHT_END])),
        )

    async def start(self) -> None:
        if not self.brain.opts.get(CONF_NIGHT_WATCH):
            return
        self._watch()
        # Pick up sensors added later without needing a reload.
        self._unsubs.append(async_track_time_interval(self.hass, self._rewatch, timedelta(minutes=30)))

    def _watch(self) -> None:
        ids = self.openings()
        if ids:
            self._watching = async_track_state_change_event(self.hass, ids, self._opened)

    async def _rewatch(self, _now: datetime) -> None:
        old = getattr(self, "_watching", None)
        if old:
            old()
        self._watch()

    def stop(self) -> None:
        super().stop()
        old = getattr(self, "_watching", None)
        if old:
            old()
            self._watching = None

    async def _opened(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None or new.state != "on" or (old is not None and old.state == "on"):
            return
        now = dt_util.now()
        if not self.is_night(now):
            return
        last = self._last.get(new.entity_id)
        if last and now - last < COOLDOWN:
            return
        self._last[new.entity_id] = now
        self.brain.record("alerts")
        text = f"Warning. {friendly(new)} opened at {now.strftime('%-I:%M %p')}."
        self.brain.log("night_watch", text)
        await self.brain.speaker.say(text, urgent=True, push=True)

    def check(self) -> dict[str, Any]:
        """Read-only sweep of everything that should normally be shut or locked."""
        issues: list[str] = []
        for s in self.hass.states.async_all("binary_sensor"):
            if s.attributes.get("device_class") in OPENING_CLASSES and s.state == "on":
                issues.append(f"{friendly(s)} is open")
        for s in self.hass.states.async_all("cover"):
            if s.attributes.get("device_class") in COVER_CLASSES and s.state in ("open", "opening"):
                issues.append(f"{friendly(s)} is open")
        for s in self.hass.states.async_all("lock"):
            if s.state in ("unlocked", "unlocking", "open", "jammed"):
                issues.append(f"{friendly(s)} is {s.state}")
        alarms = {
            friendly(s): s.state
            for s in self.hass.states.async_all("alarm_control_panel")
        }
        for name, state in alarms.items():
            if state in ("disarmed", "unknown", "unavailable"):
                issues.append(f"{name} is {state}")
        text = (
            "Everything is shut and locked." if not issues else "Security check: " + "; ".join(issues) + "."
        )
        return {"ok": not issues, "issues": issues, "text": text}
