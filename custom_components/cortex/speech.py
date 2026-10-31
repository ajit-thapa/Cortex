"""Speech router: applies the gate, picks the room, delivers, logs."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .const import CONF_MOTION, CONF_NOTIFY, CONF_SPEAKERS, CONF_TTS_ENGINE, EVENT_SPOKEN
from .gate import SpeechGate

if TYPE_CHECKING:
    from .runtime import Cortex

_LOGGER = logging.getLogger(__name__)
MOTION_WINDOW = timedelta(minutes=10)


class Speaker:
    """Single place everything that talks goes through."""

    def __init__(self, hass: HomeAssistant, brain: Cortex, gate: SpeechGate) -> None:
        self.hass = hass
        self.brain = brain
        self.gate = gate
        self.log: deque[dict] = deque(maxlen=50)

    def _area_of(self, entity_id: str) -> str | None:
        reg = er.async_get(self.hass)
        entry = reg.async_get(entity_id)
        if entry is None:
            return None
        if entry.area_id:
            return entry.area_id
        if entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            return device.area_id if device else None
        return None

    def likely_area(self) -> str | None:
        """Area with the most recent motion inside the window."""
        now = dt_util.utcnow()
        best: tuple[object, str] | None = None
        for entity_id in self.brain.opts.get(CONF_MOTION) or []:
            state = self.hass.states.get(entity_id)
            if state is None or state.state != "on":
                continue
            if now - state.last_changed > MOTION_WINDOW:
                continue
            area = self._area_of(entity_id)
            if area and (best is None or state.last_changed > best[0]):
                best = (state.last_changed, area)
        return best[1] if best else None

    def pick_targets(self, area: str | None = None) -> list[str]:
        speakers: list[str] = list(self.brain.opts.get(CONF_SPEAKERS) or [])
        if not speakers:
            return []
        area = area or self.likely_area()
        if area:
            here = [s for s in speakers if self._area_of(s) == area]
            if here:
                return here
        return speakers

    async def say(
        self, text: str, urgent: bool = False, area: str | None = None, push: bool | None = None
    ) -> dict:
        """Speak ``text`` subject to the house rules. Returns what happened."""
        now = dt_util.now()
        verdict = self.gate.decide(text, now, urgent)
        targets: list[str] = []
        pushed = False
        if verdict.speak:
            targets = self.pick_targets(area)
            for entity_id in targets:
                await self._deliver(entity_id, verdict.text)
        # Urgent messages also push to the phone unless the caller says otherwise.
        if (urgent if push is None else push) and verdict.reason not in ("empty", "banned_word"):
            pushed = await self.push(verdict.text)
        record = {
            "time": now.isoformat(timespec="seconds"),
            "text": verdict.text or text,
            "urgent": urgent,
            "spoken": verdict.speak and bool(targets),
            "reason": verdict.reason if not (verdict.speak and not targets) else "no_speakers",
            "targets": targets,
            "pushed": pushed,
        }
        self.log.appendleft(record)
        self.hass.bus.async_fire(EVENT_SPOKEN, record)
        self.brain.notify_update()
        return record

    async def _deliver(self, entity_id: str, text: str) -> None:
        domain = entity_id.split(".", 1)[0]
        try:
            if domain == "assist_satellite":
                await self.hass.services.async_call(
                    "assist_satellite",
                    "announce",
                    {"entity_id": entity_id, "message": text},
                    blocking=True,
                )
            elif domain == "media_player":
                engine = self.brain.opts.get(CONF_TTS_ENGINE)
                if not engine:
                    _LOGGER.warning("No TTS engine set, cannot speak on %s", entity_id)
                    return
                await self.hass.services.async_call(
                    "tts",
                    "speak",
                    {
                        "entity_id": engine,
                        "media_player_entity_id": entity_id,
                        "message": text,
                    },
                    blocking=True,
                )
        except HomeAssistantError as err:
            _LOGGER.warning("Could not speak on %s: %s", entity_id, err)

    async def push(self, text: str, title: str = "Cortex") -> bool:
        target = self.brain.opts.get(CONF_NOTIFY)
        if not target:
            return False
        try:
            if self.hass.states.get(target) is not None:
                await self.hass.services.async_call(
                    "notify",
                    "send_message",
                    {"entity_id": target, "message": text, "title": title},
                    blocking=True,
                )
            else:
                name = target.split(".", 1)[-1]
                await self.hass.services.async_call(
                    "notify", name, {"message": text, "title": title}, blocking=True
                )
        except HomeAssistantError as err:
            _LOGGER.warning("Push failed: %s", err)
            return False
        return True
