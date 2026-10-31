"""Named routines: steps that run on demand, on a schedule, or when an entity changes."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import Event
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.util import dt as dt_util

from .feature import Feature

_LOGGER = logging.getLogger(__name__)
MAX_DELAY = 300
DAYS = ("daily", "weekdays", "weekends")

STEP = vol.Any(
    {vol.Required("say"): str, vol.Optional("urgent", default=False): bool},
    {vol.Required("push"): str},
    {
        vol.Required("service"): vol.Match(r"^[a-z_]+\.[a-z0-9_]+$"),
        vol.Optional("target"): dict,
        vol.Optional("data"): dict,
    },
    {vol.Required("delay"): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_DELAY))},
)
ROUTINE = vol.Schema(
    {
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=60)),
        vol.Required("steps"): vol.All([STEP], vol.Length(min=1, max=30)),
        vol.Optional("schedule"): vol.Schema(
            {
                vol.Required("at"): vol.Match(r"^\d{1,2}:\d{2}(:\d{2})?$"),
                vol.Optional("days", default="daily"): vol.In(DAYS),
            }
        ),
        vol.Optional("on_state"): vol.Schema(
            {
                vol.Required("entity_id"): str,
                vol.Required("to"): str,
                vol.Optional("cooldown", default=60): vol.All(int, vol.Range(min=0)),
            }
        ),
        vol.Optional("enabled", default=True): bool,
    }
)


def day_matches(days: str, when: datetime) -> bool:
    if days == "weekdays":
        return when.weekday() < 5
    if days == "weekends":
        return when.weekday() >= 5
    return True


class Routines(Feature):
    name = "routines"

    def __init__(self, brain) -> None:
        super().__init__(brain)
        self.items: dict[str, dict[str, Any]] = {}
        self._running: set[str] = set()
        self._last: dict[str, datetime] = {}

    def load(self, data) -> None:
        self.items = (data or {}).get("items", {})

    def dump(self) -> dict[str, Any]:
        return {"items": self.items}

    async def start(self) -> None:
        self._arm()

    # ---- editing -------------------------------------------------------
    def save(self, routine: dict[str, Any]) -> dict[str, Any]:
        clean = ROUTINE(routine)
        self.items[clean["name"]] = clean
        self._arm()
        self.brain.save()
        return clean

    def delete(self, name: str) -> bool:
        if self.items.pop(name, None) is None:
            return False
        self._arm()
        self.brain.save()
        return True

    # ---- triggers ------------------------------------------------------
    def _arm(self) -> None:
        self.stop()
        for name, routine in self.items.items():
            if not routine.get("enabled", True):
                continue
            schedule = routine.get("schedule")
            if schedule:
                parts = [int(p) for p in schedule["at"].split(":")]

                async def fire(now: datetime, name=name, days=schedule.get("days", "daily")):
                    if day_matches(days, dt_util.as_local(now)):
                        await self.run(name)

                self._unsubs.append(
                    async_track_time_change(
                        self.hass, fire, hour=parts[0], minute=parts[1], second=0
                    )
                )
            trigger = routine.get("on_state")
            if trigger:

                async def changed(event: Event, name=name, trigger=trigger):
                    new = event.data.get("new_state")
                    old = event.data.get("old_state")
                    if new is None or old is None or new.state != trigger["to"] or old.state == new.state:
                        return
                    last = self._last.get(name)
                    now = dt_util.utcnow()
                    if last and (now - last).total_seconds() < trigger.get("cooldown", 60):
                        return
                    self._last[name] = now
                    await self.run(name)

                self._unsubs.append(
                    async_track_state_change_event(self.hass, [trigger["entity_id"]], changed)
                )

    # ---- running -------------------------------------------------------
    async def run(self, name: str) -> list[str]:
        routine = self.items.get(name)
        if routine is None:
            raise HomeAssistantError(f"No routine called {name}")
        if name in self._running:
            return ["already running"]
        self._running.add(name)
        results: list[str] = []
        try:
            for step in routine["steps"]:
                results.append(await self._step(step))
        finally:
            self._running.discard(name)
        self.brain.record("routines_run")
        self.brain.log("routine", f"Ran {name}")
        return results

    async def _step(self, step: dict[str, Any]) -> str:
        speaker = self.brain.speaker
        if "say" in step:
            record = await speaker.say(step["say"], urgent=step.get("urgent", False))
            return "spoke" if record["spoken"] else f"silent ({record['reason']})"
        if "push" in step:
            return "pushed" if await speaker.push(step["push"]) else "push failed"
        if "delay" in step:
            await asyncio.sleep(step["delay"])
            return f"waited {step['delay']}s"
        domain, service = step["service"].split(".", 1)
        data = dict(step.get("data") or {})
        if step.get("target"):
            data.update(step["target"])
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Routine step %s failed: %s", step["service"], err)
            return f"error: {err}"
        return step["service"]
