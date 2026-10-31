"""Motion lights: switch lights on with motion when it is dark, off after a delay."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.core import Event
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .feature import Feature

RULE = vol.Schema(
    {
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=60)),
        vol.Required("motion"): vol.All([str], vol.Length(min=1)),
        vol.Required("lights"): vol.All([str], vol.Length(min=1)),
        vol.Optional("delay", default=180): vol.All(int, vol.Range(min=10, max=7200)),
        vol.Optional("brightness", default=100): vol.All(int, vol.Range(min=1, max=100)),
        vol.Optional("only_dark", default=True): bool,
        vol.Optional("lux_sensor"): str,
        vol.Optional("lux_below", default=30): vol.Coerce(float),
    }
)


class MotionLights(Feature):
    name = "motion_lights"

    def __init__(self, brain) -> None:
        super().__init__(brain)
        self.rules: dict[str, dict[str, Any]] = {}
        self._timers: dict[str, Callable[[], None]] = {}
        self._we_turned_on: dict[str, set[str]] = {}

    def load(self, data) -> None:
        self.rules = (data or {}).get("rules", {})

    def dump(self) -> dict[str, Any]:
        return {"rules": self.rules}

    async def start(self) -> None:
        self._arm()

    def stop(self) -> None:
        super().stop()
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    def save(self, rule: dict[str, Any]) -> dict[str, Any]:
        clean = RULE(rule)
        self.rules[clean["name"]] = clean
        self._arm()
        self.brain.save()
        return clean

    def delete(self, name: str) -> bool:
        if self.rules.pop(name, None) is None:
            return False
        self._arm()
        self.brain.save()
        return True

    def _arm(self) -> None:
        super().stop()
        for name, rule in self.rules.items():

            async def moved(event: Event, name=name, rule=rule) -> None:
                new = event.data.get("new_state")
                if new is None:
                    return
                if new.state == "on":
                    await self._on(name, rule)
                elif new.state == "off" and not self._any_motion(rule):
                    self._schedule_off(name, rule)

            self._unsubs.append(
                async_track_state_change_event(self.hass, rule["motion"], moved)
            )

    def _any_motion(self, rule: dict[str, Any]) -> bool:
        return any(
            (s := self.hass.states.get(m)) is not None and s.state == "on" for m in rule["motion"]
        )

    def _is_dark(self, rule: dict[str, Any]) -> bool:
        if not rule.get("only_dark", True):
            return True
        lux = self.hass.states.get(rule.get("lux_sensor") or "")
        if lux is not None:
            try:
                return float(lux.state) < rule.get("lux_below", 30)
            except ValueError:
                pass
        sun = self.hass.states.get("sun.sun")
        return sun is None or sun.state == "below_horizon"

    async def _on(self, name: str, rule: dict[str, Any]) -> None:
        cancel = self._timers.pop(name, None)
        if cancel:
            cancel()
        if not self._is_dark(rule):
            return
        for light in rule["lights"]:
            state = self.hass.states.get(light)
            if state is not None and state.state != "on":
                self._we_turned_on.setdefault(name, set()).add(light)
        try:
            await self.hass.services.async_call(
                "light",
                "turn_on",
                {"entity_id": rule["lights"], "brightness_pct": rule.get("brightness", 100)},
                blocking=True,
            )
        except HomeAssistantError:
            return
        self.brain.log("motion_light", f"{name}: on")

    def _schedule_off(self, name: str, rule: dict[str, Any]) -> None:
        cancel = self._timers.pop(name, None)
        if cancel:
            cancel()

        async def off(_now) -> None:
            self._timers.pop(name, None)
            if self._any_motion(rule):
                return
            ours = sorted(self._we_turned_on.pop(name, set()))
            if ours:
                try:
                    await self.hass.services.async_call(
                        "light", "turn_off", {"entity_id": ours}, blocking=True
                    )
                except HomeAssistantError:
                    return
                self.brain.log("motion_light", f"{name}: off")

        self._timers[name] = async_call_later(self.hass, rule.get("delay", 180), off)
