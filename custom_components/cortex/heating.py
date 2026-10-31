"""Heating pre-warm: start early enough that a room is at temperature by a set time."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .feature import Feature
from .routines import DAYS, day_matches

RULE = vol.Schema(
    {
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=60)),
        vol.Required("climate"): str,
        vol.Required("target"): vol.Coerce(float),
        vol.Required("ready_by"): vol.Match(r"^\d{1,2}:\d{2}(:\d{2})?$"),
        vol.Optional("days", default="daily"): vol.In(DAYS),
        vol.Optional("hvac_mode", default="heat"): str,
        vol.Optional("persons", default=[]): [str],
        vol.Optional("rate", default=0.05): vol.All(vol.Coerce(float), vol.Range(min=0.005, max=1)),
    }
)
MARGIN_MIN = 5


def lead_minutes(current: float, target: float, rate_per_min: float) -> float:
    """Minutes of heating needed to climb from ``current`` to ``target``."""
    if target <= current or rate_per_min <= 0:
        return 0.0
    return (target - current) / rate_per_min


class Heating(Feature):
    name = "heating"

    def __init__(self, brain) -> None:
        super().__init__(brain)
        self.rules: dict[str, dict[str, Any]] = {}
        self.started: dict[str, dict[str, Any]] = {}

    def load(self, data) -> None:
        data = data or {}
        self.rules = data.get("rules", {})
        self.started = data.get("started", {})

    def dump(self) -> dict[str, Any]:
        return {"rules": self.rules, "started": self.started}

    async def start(self) -> None:
        self._unsubs.append(async_track_time_change(self.hass, self._tick, second=20))

    def save(self, rule: dict[str, Any]) -> dict[str, Any]:
        clean = RULE(rule)
        self.rules[clean["name"]] = clean
        self.brain.save()
        return clean

    def delete(self, name: str) -> bool:
        self.started.pop(name, None)
        if self.rules.pop(name, None) is None:
            return False
        self.brain.save()
        return True

    def _someone_home(self, rule: dict[str, Any]) -> bool:
        persons = rule.get("persons") or []
        if not persons:
            return True
        return any(
            (s := self.hass.states.get(p)) is not None and s.state == "home" for p in persons
        )

    def _current(self, rule: dict[str, Any]) -> float | None:
        state = self.hass.states.get(rule["climate"])
        if state is None:
            return None
        try:
            return float(state.attributes.get("current_temperature"))
        except (TypeError, ValueError):
            return None

    async def _tick(self, now: datetime) -> None:
        now = dt_util.as_local(now)
        for name, rule in list(self.rules.items()):
            current = self._current(rule)
            if current is None:
                continue
            await self._learn(name, rule, current, now)
            if not day_matches(rule.get("days", "daily"), now):
                continue
            hh, mm = (int(p) for p in rule["ready_by"].split(":")[:2])
            ready = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            begin = ready - timedelta(
                minutes=lead_minutes(current, rule["target"], rule["rate"]) + MARGIN_MIN
            )
            started = self.started.get(name)
            if started and started.get("date") == now.date().isoformat():
                continue
            if begin <= now < ready and current < rule["target"] and self._someone_home(rule):
                await self._start(name, rule, current, now)

    async def _start(self, name: str, rule: dict[str, Any], current: float, now: datetime) -> None:
        try:
            await self.hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": rule["climate"], "hvac_mode": rule.get("hvac_mode", "heat")},
                blocking=True,
            )
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": rule["climate"], "temperature": rule["target"]},
                blocking=True,
            )
        except HomeAssistantError:
            return
        self.started[name] = {"date": now.date().isoformat(), "at": now.isoformat(), "from": current}
        self.brain.save()
        self.brain.log("heating", f"{name}: pre-warm from {current:g} to {rule['target']:g}")

    async def _learn(self, name: str, rule: dict[str, Any], current: float, now: datetime) -> None:
        """Once the room reaches target, fold the observed warm-up speed into the rate."""
        started = self.started.get(name)
        if not started or started.get("learned") or current < rule["target"] - 0.2:
            return
        began = dt_util.parse_datetime(started["at"])
        minutes = (now - began).total_seconds() / 60 if began else 0
        gained = current - float(started.get("from", current))
        started["learned"] = True
        if minutes >= 5 and gained > 0.3:
            rule["rate"] = round(0.7 * rule["rate"] + 0.3 * (gained / minutes), 4)
        self.brain.save()
