"""Runtime object tying memory, speech, energy, safety, watches and reminders."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AGENT,
    CONF_AI_PER_HOUR,
    CONF_AI_TASK,
    CONF_HEALTH_IGNORE,
    CONF_AUTO_EXPORT,
    CONF_AUTO_TOPUP,
    CONF_BANNED,
    CONF_DEDUPE,
    CONF_EV_GATE,
    CONF_EV_PLUG,
    CONF_EV_SOC,
    CONF_EV_TARGET,
    CONF_HOLIDAYS,
    CONF_PV_TODAY,
    CONF_PV_TOMORROW,
    CONF_SOC,
    CONF_QUIET_END,
    CONF_QUIET_START,
    DEFAULTS,
    DOMAIN,
    SAFETY_CLASSES,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
)
from .autopilot import Autopilot
from .backup import Backup
from .briefing import Briefing
from .energy import EnergyBrain
from .heating import Heating
from .learning import Learning
from .motion_lights import MotionLights
from .routines import Routines
from .security import Security
from .timeline import Timeline
from .visitors import PROMPT as LOOK_PROMPT, Visitors
from .gate import SpeechGate, parse_time
from .memory import MemoryBook
from .speech import Speaker

_LOGGER = logging.getLogger(__name__)
HEALTH_EVERY = timedelta(minutes=5)
SOURCE_KEYS = (
    CONF_SOC, CONF_PV_TODAY, CONF_PV_TOMORROW, CONF_EV_SOC, CONF_EV_PLUG,
    CONF_EV_TARGET, CONF_HOLIDAYS,
)
LOW_BATTERY = 15
OFFLINE_AFTER = timedelta(minutes=30)  # a restart or a Wi-Fi blip is not a fault
VOICE_STATES = {"listening", "processing", "responding"}


class Cortex:
    """One per config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.opts: dict[str, Any] = {}
        self.store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.book = MemoryBook()
        self.watches: list[dict[str, Any]] = []
        self.reminders: list[dict[str, Any]] = []
        self.gate = SpeechGate()
        self.speaker = Speaker(hass, self, self.gate)
        self.energy = EnergyBrain(hass, self)
        self.timeline = Timeline(self)
        self.routines = Routines(self)
        self.learning = Learning(self)
        self.motion_lights = MotionLights(self)
        self.heating = Heating(self)
        self.security = Security(self)
        self.visitors = Visitors(self)
        self.briefing = Briefing(self)
        self.backup = Backup(self)
        self.autopilot = Autopilot(self)
        self._ai_calls: deque[datetime] = deque()
        self.snapshot: dict[str, Any] = {}
        self.health: list[str] = []
        self._unsubs: list[Callable[[], None]] = []
        self._timers: dict[str, Callable[[], None]] = {}
        self._known_issues: set[str] = set()
        self._offline_since: dict[str, datetime] = {}

    @property
    def features(self):
        return (
            self.timeline, self.routines, self.learning, self.motion_lights,
            self.heating, self.security, self.visitors, self.briefing, self.backup, self.autopilot,
        )

    # ---- lifecycle ------------------------------------------------------
    def load_options(self) -> None:
        self.opts = {**DEFAULTS, **self.entry.data, **self.entry.options}
        # Older installs saved the charger's raw sensor; the wall connector's total power is the real EV load.
        if self.opts.get("studio_ev") == "sensor.tesla_wall_connector_ev_charger":
            self.opts["studio_ev"] = "sensor.tesla_wall_connector_total_power"
        self.gate.quiet_start = parse_time(str(self.opts[CONF_QUIET_START]))
        self.gate.quiet_end = parse_time(str(self.opts[CONF_QUIET_END]))
        self.gate.dedupe_minutes = int(self.opts[CONF_DEDUPE])
        self.gate.banned_words = tuple(
            w.strip() for w in str(self.opts[CONF_BANNED]).split(",") if w.strip()
        )

    async def async_start(self) -> None:
        self.load_options()
        data = await self.store.async_load() or {}
        self.book = MemoryBook.from_data(data.get("memory"))
        self.watches = list(data.get("watches", []))
        self.reminders = list(data.get("reminders", []))
        saved = data.get("features", {})
        for feature in self.features:
            feature.load(saved.get(feature.name))
        self._schedule_reminders()
        self._track_watches()
        self._schedule_energy()
        self._track_safety()
        self._unsubs.append(
            async_track_time_interval(self.hass, self._tick_health, HEALTH_EVERY)
        )
        self._unsubs.append(
            async_track_time_change(self.hass, self._tick_minute, second=5)
        )
        self._track_sources()
        self._track_voice()
        for feature in self.features:
            await feature.start()
        self.refresh()
        self.hass.async_create_task(self.run_health())

    def _track_sources(self) -> None:
        """Refresh as soon as any energy input appears or changes.

        Cortex can start before the battery, EV and forecast integrations, so
        waiting for the minute tick leaves sensors unknown after a restart.
        """
        ids = sorted(
            {
                self.opts[key]
                for key in SOURCE_KEYS
                if self.opts.get(key)
            }
        )
        if ids:
            self._unsubs.append(
                async_track_state_change_event(self.hass, ids, self._on_source)
            )

    @callback
    def _on_source(self, _event: Event) -> None:
        self.refresh()

    @callback
    def async_stop(self) -> None:
        for feature in self.features:
            feature.stop()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in self._timers.values():
            unsub()
        self._timers.clear()
        self.store.async_delay_save(self._data, 0)

    def _data(self) -> dict[str, Any]:
        return {
            "memory": self.book.to_data(),
            "watches": self.watches,
            "reminders": self.reminders,
            "features": {f.name: f.dump() for f in self.features},
        }

    def export_data(self) -> dict[str, Any]:
        return self._data()

    async def import_data(self, data: dict[str, Any]) -> None:
        """Replace everything remembered with ``data`` (from a backup)."""
        for feature in self.features:
            feature.stop()
        for unsub in self._timers.values():
            unsub()
        self._timers.clear()
        self.book = MemoryBook.from_data(data.get("memory"))
        self.watches = list(data.get("watches", []))
        self.reminders = list(data.get("reminders", []))
        saved = data.get("features", {})
        for feature in self.features:
            feature.load(saved.get(feature.name))
        self._schedule_reminders()
        self._track_watches()
        for feature in self.features:
            await feature.start()
        self.save()

    # ---- bookkeeping ----------------------------------------------------
    def log(self, kind: str, text: str) -> None:
        self.timeline.add(kind, text)

    def record(self, key: str, value: float = 1) -> None:
        self.timeline.record(key, value)

    # ---- AI helpers (always through the user's own HA agents) -----------
    def ai_allowed(self) -> bool:
        """True if another model call fits the hourly budget; counts the call."""
        now = dt_util.utcnow()
        while self._ai_calls and now - self._ai_calls[0] > timedelta(hours=1):
            self._ai_calls.popleft()
        if len(self._ai_calls) >= int(self.opts.get(CONF_AI_PER_HOUR) or 0):
            return False
        self._ai_calls.append(now)
        return True

    async def ask_agent(self, prompt: str) -> str:
        data: dict[str, Any] = {"text": prompt}
        if self.opts.get(CONF_AGENT):
            data["agent_id"] = self.opts[CONF_AGENT]
        result = await self.hass.services.async_call(
            "conversation", "process", data, blocking=True, return_response=True
        )
        return (
            ((result or {}).get("response", {}).get("speech", {}).get("plain", {}).get("speech", ""))
            or ""
        ).strip()

    async def look(self, camera: str, question: str | None) -> str:
        """Describe what a camera sees using the configured AI Task entity."""
        task = self.opts.get(CONF_AI_TASK)
        if not task:
            raise HomeAssistantError("No AI Task entity configured")
        if not self.ai_allowed():
            raise HomeAssistantError("AI call budget used up for this hour")
        spot = self.visitors.spots.get(camera)
        where = f" ({spot})" if spot else ""
        instructions = (
            LOOK_PROMPT.format(where=where)
            if question is None
            else f"This is a still image from a home camera{where}. {question} Answer briefly."
        )
        result = await self.hass.services.async_call(
            "ai_task",
            "generate_data",
            {
                "entity_id": task,
                "task_name": "cortex look",
                "instructions": instructions,
                "attachments": [
                    {"media_content_id": f"media-source://camera/{camera}", "media_content_type": "image/jpeg"}
                ],
            },
            blocking=True,
            return_response=True,
        )
        return str((result or {}).get("data", "")).strip()

    @callback
    def save(self) -> None:
        self.store.async_delay_save(self._data, 3)
        self.notify_update()

    # ---- snapshot -------------------------------------------------------
    @callback
    def refresh(self) -> None:
        self.snapshot = self.energy.snapshot()
        snap = self.snapshot
        if snap.get("battery_soc") is not None:
            self.timeline.record("soc_min", snap["battery_soc"])
            self.timeline.record("soc_max", snap["battery_soc"])
        if snap.get("pv_today") is not None:
            self.timeline.record("pv_forecast", snap["pv_today"])
        self.notify_update()

    @callback
    def notify_update(self) -> None:
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    async def _tick_minute(self, _now: datetime) -> None:
        self.refresh()

    # ---- memory ---------------------------------------------------------
    def remember(self, text: str, category: str = "fact", source: str | None = None):
        memory = self.book.add(text, category, source)
        self.save()
        return memory

    def forget(self, ident: str):
        memory = self.book.forget(ident)
        if memory:
            self.save()
        return memory

    # ---- reminders ------------------------------------------------------
    def add_reminder(self, message: str, at: datetime) -> dict[str, Any]:
        item = {"id": uuid.uuid4().hex[:8], "message": message, "at": at.isoformat()}
        self.reminders.append(item)
        self._arm(item)
        self.save()
        return item

    def _schedule_reminders(self) -> None:
        for item in list(self.reminders):
            self._arm(item)

    def _arm(self, item: dict[str, Any]) -> None:
        when = dt_util.parse_datetime(item["at"])
        if when is None:
            self.reminders.remove(item)
            return
        if when <= dt_util.now():
            # Missed while offline: fire shortly, it is still worth saying.
            when = dt_util.now() + timedelta(seconds=20)

        async def _fire(_now: datetime, item=item) -> None:
            self._timers.pop(item["id"], None)
            if item in self.reminders:
                self.reminders.remove(item)
            self.record("reminders")
            self.save()
            await self.speaker.say(f"Reminder: {item['message']}", urgent=True, push=True)

        self._timers[item["id"]] = async_track_point_in_time(self.hass, _fire, when)

    def cancel_reminder(self, ident: str) -> bool:
        for item in self.reminders:
            if item["id"] == ident:
                self.reminders.remove(item)
                unsub = self._timers.pop(ident, None)
                if unsub:
                    unsub()
                self.save()
                return True
        return False

    # ---- watches --------------------------------------------------------
    def add_watch(
        self,
        entity_id: str,
        message: str,
        to_state: str | None = None,
        cooldown: int = 600,
        urgent: bool = False,
        ai: bool = False,
        camera: str | None = None,
    ) -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex[:8],
            "entity_id": entity_id,
            "message": message,
            "to_state": to_state,
            "cooldown": cooldown,
            "urgent": urgent,
            "ai": ai,
            "camera": camera,
            "last": None,
        }
        self.watches.append(item)
        self._track_watches()
        self.save()
        return item

    def remove_watch(self, ident: str) -> bool:
        before = len(self.watches)
        self.watches = [w for w in self.watches if w["id"] != ident]
        if len(self.watches) != before:
            self._track_watches()
            self.save()
            return True
        return False

    def _track_watches(self) -> None:
        unsub = self._timers.pop("watches", None)
        if unsub:
            unsub()
        ids = sorted({w["entity_id"] for w in self.watches})
        if ids:
            self._timers["watches"] = async_track_state_change_event(
                self.hass, ids, self._on_watched
            )

    async def _on_watched(self, event: Event) -> None:
        new = event.data.get("new_state")
        if new is None:
            return
        now = dt_util.utcnow()
        for item in self.watches:
            if item["entity_id"] != new.entity_id:
                continue
            if item["to_state"] and new.state != item["to_state"]:
                continue
            last = dt_util.parse_datetime(item["last"]) if item["last"] else None
            if last and (now - last).total_seconds() < item["cooldown"]:
                continue
            item["last"] = now.isoformat()
            name = new.attributes.get("friendly_name", new.entity_id)
            text = item["message"].format(name=name, state=new.state)
            if item.get("camera"):
                try:
                    text += " " + (await self.look(item["camera"], "What is happening? One short sentence.")).rstrip(".") + "."
                except HomeAssistantError:
                    pass
            if item.get("ai") and self.ai_allowed():
                try:
                    remark = await self.ask_agent(
                        f"In one short, calm sentence, add a helpful remark about this household alert: {text}"
                    )
                    if remark:
                        text += " " + remark
                except HomeAssistantError:
                    pass
            self.save()
            await self.speaker.say(text, urgent=item["urgent"])

    # ---- energy schedule ------------------------------------------------
    def _schedule_energy(self) -> None:
        plan = self.energy.plan()
        o = self.opts

        async def top_start(_n: datetime) -> None:
            if o[CONF_AUTO_TOPUP] and not self.autopilot.controls:
                await self.energy.start_topup()

        async def top_stop(_n: datetime) -> None:
            if o[CONF_AUTO_TOPUP] and not self.autopilot.controls:
                await self.energy.stop("Force Charge")

        async def exp_start(_n: datetime) -> None:
            if o[CONF_AUTO_EXPORT] and not self.autopilot.controls:
                await self.energy.start_export()

        async def exp_stop(_n: datetime) -> None:
            if o[CONF_AUTO_EXPORT] and not self.autopilot.controls:
                await self.energy.stop("Force Discharge")

        s_start, s_end = plan.shoulder_window
        f_start, f_end = plan.fit_evening_window
        for fn, hour in ((top_start, s_start), (top_stop, s_end), (exp_start, f_start), (exp_stop, f_end % 24)):
            self._unsubs.append(
                async_track_time_change(self.hass, fn, hour=hour, minute=0, second=0)
            )
        plug = o.get(CONF_EV_PLUG)
        if plug:

            async def on_plug(event: Event) -> None:
                new = event.data.get("new_state")
                if o[CONF_EV_GATE] and new is not None and new.state == "on":
                    await self.energy.ev_plugged_in(plan.shoulder_window)

            self._unsubs.append(async_track_state_change_event(self.hass, [plug], on_plug))

    # ---- safety and health ---------------------------------------------
    def _safety_entities(self) -> list[str]:
        return [
            s.entity_id
            for s in self.hass.states.async_all("binary_sensor")
            if s.attributes.get("device_class") in SAFETY_CLASSES
        ]

    def _track_safety(self) -> None:
        ids = self._safety_entities()
        if ids:
            self._unsubs.append(async_track_state_change_event(self.hass, ids, self._on_alarm))

    async def _on_alarm(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None or new.state != "on" or (old is not None and old.state == "on"):
            return
        self.record("alerts")
        phrase = SAFETY_CLASSES.get(new.attributes.get("device_class", ""), "has raised an alert")
        name = new.attributes.get("friendly_name", new.entity_id)
        await self.speaker.say(f"Warning. {name} {phrase}.", urgent=True, push=True)

    async def _tick_health(self, _now: datetime) -> None:
        await self.run_health()

    async def run_health(self) -> list[str]:
        issues: list[str] = []
        ignore = set(self.opts.get(CONF_HEALTH_IGNORE) or [])
        for state in self.hass.states.async_all():
            if state.entity_id in ignore:
                continue
            domain = state.domain
            name = state.attributes.get("friendly_name", state.entity_id)
            dc = state.attributes.get("device_class")
            if domain == "binary_sensor" and dc == "battery" and state.state == "on":
                issues.append(f"{name} has a low battery")
            elif domain == "sensor" and dc == "battery" and state.attributes.get("unit_of_measurement") == "%":
                try:
                    if float(state.state) < LOW_BATTERY:
                        issues.append(f"{name} battery at {float(state.state):.0f}%")
                except ValueError:
                    pass
            elif domain == "update" and state.state == "on":
                issues.append(f"Update available for {name}")
        now = dt_util.utcnow()
        offline: list[str] = []
        seen: set[str] = set()
        for s in self.hass.states.async_all(("light", "switch", "climate", "lock", "cover")):
            if s.state != "unavailable" or s.entity_id in ignore:
                continue
            seen.add(s.entity_id)
            since = self._offline_since.setdefault(s.entity_id, now)
            if now - since >= OFFLINE_AFTER:
                offline.append(s.attributes.get("friendly_name", s.entity_id))
        for gone in set(self._offline_since) - seen:
            del self._offline_since[gone]
        if offline:
            offline.sort()
            if len(offline) <= 3:
                issues.append(f"{', '.join(offline)} {'is' if len(offline) == 1 else 'are'} offline")
            else:
                issues.append(f"{len(offline)} devices are offline: {', '.join(offline[:3])} and {len(offline) - 3} more")
        self.health = sorted(issues)
        fresh = {i for i in issues if "Update available" not in i} - self._known_issues
        self._known_issues = {i for i in issues if "Update available" not in i}
        if fresh:
            await self.speaker.push("; ".join(sorted(fresh)), title="Cortex house health")
        self.notify_update()
        return self.health

    # ---- briefing -------------------------------------------------------
    def briefing_text(self) -> str:
        return self.briefing.build()

    # ---- voice activity -------------------------------------------------
    def _track_voice(self) -> None:
        ids = [s.entity_id for s in self.hass.states.async_all("assist_satellite")]
        if ids:
            self._unsubs.append(async_track_state_change_event(self.hass, ids, self._on_voice))

    @callback
    def _on_voice(self, event: Event) -> None:
        new = event.data.get("new_state")
        if new is not None and new.state in VOICE_STATES:
            self.speaker.note_voice(new.entity_id)
