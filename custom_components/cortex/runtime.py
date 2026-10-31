"""Runtime object tying memory, speech, energy, safety, watches and reminders."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
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
from .energy import EnergyBrain
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
        self.snapshot: dict[str, Any] = {}
        self.health: list[str] = []
        self._unsubs: list[Callable[[], None]] = []
        self._timers: dict[str, Callable[[], None]] = {}
        self._known_issues: set[str] = set()

    # ---- lifecycle ------------------------------------------------------
    def load_options(self) -> None:
        self.opts = {**DEFAULTS, **self.entry.data, **self.entry.options}
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
        }

    @callback
    def save(self) -> None:
        self.store.async_delay_save(self._data, 3)
        self.notify_update()

    # ---- snapshot -------------------------------------------------------
    @callback
    def refresh(self) -> None:
        self.snapshot = self.energy.snapshot()
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
    ) -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex[:8],
            "entity_id": entity_id,
            "message": message,
            "to_state": to_state,
            "cooldown": cooldown,
            "urgent": urgent,
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
            self.save()
            await self.speaker.say(text, urgent=item["urgent"])

    # ---- energy schedule ------------------------------------------------
    def _schedule_energy(self) -> None:
        plan = self.energy.plan()
        o = self.opts

        async def top_start(_n: datetime) -> None:
            if o[CONF_AUTO_TOPUP]:
                await self.energy.start_topup()

        async def top_stop(_n: datetime) -> None:
            if o[CONF_AUTO_TOPUP]:
                await self.energy.stop("Force Charge")

        async def exp_start(_n: datetime) -> None:
            if o[CONF_AUTO_EXPORT]:
                await self.energy.start_export()

        async def exp_stop(_n: datetime) -> None:
            if o[CONF_AUTO_EXPORT]:
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
        phrase = SAFETY_CLASSES.get(new.attributes.get("device_class", ""), "has raised an alert")
        name = new.attributes.get("friendly_name", new.entity_id)
        await self.speaker.say(f"Warning. {name} {phrase}.", urgent=True, push=True)

    async def _tick_health(self, _now: datetime) -> None:
        await self.run_health()

    async def run_health(self) -> list[str]:
        issues: list[str] = []
        for state in self.hass.states.async_all():
            domain = state.domain
            name = state.attributes.get("friendly_name", state.entity_id)
            dc = state.attributes.get("device_class")
            if domain == "binary_sensor" and dc == "battery" and state.state == "on":
                issues.append(f"{name} has a low battery")
            elif domain == "sensor" and dc == "battery":
                try:
                    if float(state.state) < LOW_BATTERY:
                        issues.append(f"{name} battery at {float(state.state):.0f}%")
                except ValueError:
                    pass
            elif domain == "update" and state.state == "on":
                issues.append(f"Update available for {name}")
        unavailable = [
            s for s in self.hass.states.async_all(("light", "switch", "climate", "lock", "cover"))
            if s.state == "unavailable"
        ]
        if unavailable:
            issues.append(f"{len(unavailable)} devices are offline")
        self.health = sorted(issues)
        fresh = {i for i in issues if "Update available" not in i} - self._known_issues
        self._known_issues = {i for i in issues if "Update available" not in i}
        if fresh:
            await self.speaker.push("; ".join(sorted(fresh)), title="Cortex house health")
        self.notify_update()
        return self.health

    # ---- briefing -------------------------------------------------------
    def briefing_text(self) -> str:
        self.refresh()
        snap, now = self.snapshot, dt_util.now()
        hour = now.hour
        greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        parts = [f"{greet}."]
        parts.append(
            f"Power is {snap['period'].replace('_', ' ')} at {snap['import_rate']:g} cents, "
            f"changing to {snap['next_period'].replace('_', ' ')} at "
            f"{snap['next_change'].astimezone().strftime('%-I:%M %p')}."
        )
        if snap["pv_today"] is not None:
            parts.append(f"Solar forecast is {snap['pv_today']:.0f} kilowatt hours, a {snap['solar_day']} day.")
        if snap["battery_soc"] is not None:
            parts.append(f"The battery is at {snap['battery_soc']:.0f} percent.")
        if snap["pv_shortfall"] is not None and snap["pv_shortfall"] > 0:
            parts.append(f"Solar is short by {snap['pv_shortfall']:.0f} kilowatt hours, so a grid top-up is likely.")
        today = [r for r in self.reminders if (dt_util.parse_datetime(r["at"]) or now).date() == now.date()]
        if today:
            parts.append("Reminders today: " + "; ".join(r["message"] for r in today) + ".")
        if self.health:
            parts.append(f"{len(self.health)} things need attention in the house.")
        return " ".join(parts)
