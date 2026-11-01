"""Energy brain: tariff-aware snapshot and battery/EV actions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from . import tariff
from .const import (
    CONF_BATTERY_KWH,
    CONF_CHARGE_TARGET,
    CONF_DISCHARGE_TARGET,
    CONF_DURATION,
    CONF_EV_KWH,
    CONF_EV_PLUG,
    CONF_EV_SOC,
    CONF_EV_START,
    CONF_EV_TARGET,
    CONF_EXPORT_FLOOR,
    CONF_EXPORT_KW,
    CONF_EXPORT_MIN_SOC,
    CONF_FIT_EVENING,
    CONF_FIT_MORNING,
    CONF_FIT_OTHER,
    CONF_HOLIDAYS,
    CONF_LOW_SOLAR,
    CONF_MODE,
    CONF_POWER,
    CONF_PV_TODAY,
    CONF_PV_TOMORROW,
    CONF_RATE_HIGH_PEAK,
    CONF_RATE_LOW_PEAK,
    CONF_RATE_OFF_PEAK,
    CONF_RATE_SHOULDER,
    CONF_RESERVE,
    CONF_SOC,
    CONF_STOP,
    CONF_SUPPLY,
    CONF_TOPUP_KW,
)

if TYPE_CHECKING:
    from .runtime import Cortex

_LOGGER = logging.getLogger(__name__)
UNKNOWN = ("unknown", "unavailable", "none", "")


class EnergyBrain:
    """Reads the house, applies the tariff, and (optionally) drives the battery."""

    def __init__(self, hass: HomeAssistant, brain: Cortex) -> None:
        self.hass = hass
        self.brain = brain

    # ---- inputs ---------------------------------------------------------
    def plan(self) -> tariff.Plan:
        o = self.brain.opts
        return tariff.Plan(
            high_season_peak=float(o[CONF_RATE_HIGH_PEAK]),
            low_season_peak=float(o[CONF_RATE_LOW_PEAK]),
            shoulder=float(o[CONF_RATE_SHOULDER]),
            off_peak=float(o[CONF_RATE_OFF_PEAK]),
            supply_charge=float(o[CONF_SUPPLY]),
            fit_evening=float(o[CONF_FIT_EVENING]),
            fit_morning=float(o[CONF_FIT_MORNING]),
            fit_off_peak=float(o[CONF_FIT_OTHER]),
        )

    def _num(self, key: str) -> float | None:
        entity_id = self.brain.opts.get(key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNKNOWN:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _is_on(self, key: str) -> bool:
        entity_id = self.brain.opts.get(key)
        state = self.hass.states.get(entity_id) if entity_id else None
        return state is not None and state.state == "on"

    def is_holiday(self, day: date) -> bool:
        """Today's holiday flag comes from the calendar; future days are unknown."""
        entity_id = self.brain.opts.get(CONF_HOLIDAYS)
        if not entity_id or day != dt_util.now().date():
            return False
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == "on"

    @staticmethod
    def _tomorrow_estimate(state: Any) -> float | None:
        """Prefer the central (P50) estimate when the sensor offers one."""
        if state is None or state.state in UNKNOWN:
            return None
        estimate = state.attributes.get("estimate")
        try:
            return float(estimate if estimate is not None else state.state)
        except (TypeError, ValueError):
            return None

    # ---- snapshot -------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        o = self.brain.opts
        plan = self.plan()
        now = dt_util.now()
        holiday = self.is_holiday(now.date())
        cur = tariff.period(now, plan, holiday)
        change_at, change_to = tariff.next_change(now, plan, self.is_holiday)
        bat_kwh = float(o[CONF_BATTERY_KWH])
        ev_kwh = float(o[CONF_EV_KWH])
        reserve = float(o[CONF_RESERVE])
        soc = self._num(CONF_SOC)
        ev_soc = self._num(CONF_EV_SOC)
        ev_target = self._num(CONF_EV_TARGET)
        pv = self._num(CONF_PV_TODAY)
        pv_state = self.hass.states.get(o.get(CONF_PV_TOMORROW) or "")
        tomorrow = self._tomorrow_estimate(pv_state)
        plugged = self._is_on(CONF_EV_PLUG)
        shortfall = (
            tariff.pv_shortfall(pv, soc, bat_kwh, plugged, ev_soc, ev_target, ev_kwh)
            if pv is not None and soc is not None
            else None
        )
        export_cover = tariff.export_kwh_to_cover(plan)
        data: dict[str, Any] = {
            "period": cur,
            "import_rate": tariff.import_rate(now, plan, holiday),
            "feed_in_rate": tariff.feed_in_rate(now, plan),
            "next_period": change_to,
            "next_change": change_at,
            "business_day": tariff.is_business_day(now.date(), holiday),
            "high_season": tariff.is_high_season(now.date(), plan),
            "export_to_cover": export_cover,
            "daily_charge": round(plan.supply_charge / 100, 2),
            "pv_today": pv,
            "pv_tomorrow": tomorrow,
            "solar_day": tariff.solar_day(pv, float(o[CONF_LOW_SOLAR])),
            "pv_shortfall": shortfall,
            "battery_soc": soc,
            "battery_stored": tariff.stored_kwh(soc, bat_kwh) if soc is not None else None,
            "battery_usable": tariff.usable_kwh(soc, bat_kwh, reserve) if soc is not None else None,
            "battery_room": tariff.room_kwh(soc, bat_kwh) if soc is not None else None,
            "ev_soc": ev_soc,
            "ev_stored": tariff.stored_kwh(ev_soc, ev_kwh) if ev_soc is not None else None,
            "ev_room": tariff.room_kwh(ev_soc, ev_kwh) if ev_soc is not None else None,
            "ev_plugged": plugged,
            "low_solar": float(o[CONF_LOW_SOLAR]),
        }
        data["storage_summary"] = self._storage_summary(data, bat_kwh, ev_kwh)
        data["summary"] = self._summary(data)
        return data

    @staticmethod
    def _storage_summary(d: dict[str, Any], bat_kwh: float, ev_kwh: float) -> str:
        parts = []
        if d["battery_soc"] is not None:
            parts.append(
                f"Battery {d['battery_stored']}/{bat_kwh:g} kWh "
                f"({d['battery_soc']:.0f}%, room {d['battery_room']} kWh)"
            )
        if d["ev_soc"] is not None:
            parts.append(
                f"EV {d['ev_stored']}/{ev_kwh:g} kWh "
                f"({d['ev_soc']:.0f}%, room {d['ev_room']} kWh)"
            )
        return " | ".join(parts)[:255]

    @staticmethod
    def _summary(d: dict[str, Any]) -> str:
        name = d["period"].replace("_", " ")
        parts = [
            f"{name.capitalize()} {d['import_rate']:g}c",
            f"next {d['next_period'].replace('_', ' ')} {d['next_change'].astimezone().strftime('%H:%M')}",
        ]
        if d["feed_in_rate"] >= 20:
            parts.insert(0, f"Export {d['feed_in_rate']:g}c now")
        if d["pv_today"] is not None:
            parts.append(f"solar {d['pv_today']:.0f} kWh ({d['solar_day']})")
        if d["battery_soc"] is not None:
            parts.append(f"battery {d['battery_soc']:.0f}%")
        parts.append(f"daily charge ${d['daily_charge']:.2f}")
        return " | ".join(parts)[:255]

    # ---- actions --------------------------------------------------------
    async def _set(self, domain: str, service: str, key: str, **data: Any) -> bool:
        entity_id = self.brain.opts.get(key)
        if not entity_id:
            return False
        try:
            await self.hass.services.async_call(
                domain, service, {"entity_id": entity_id, **data}, blocking=True
            )
        except HomeAssistantError as err:
            _LOGGER.warning("%s.%s on %s failed: %s", domain, service, entity_id, err)
            return False
        return True

    async def start_topup(
        self, force: bool = False, kw: float | None = None, target: float | None = None
    ) -> str:
        """Charge the battery from the grid during the cheap shoulder window."""
        snap = self.snapshot()
        short = snap["pv_shortfall"]
        if not force and (short is None or short <= 0):
            return "skipped: forecast solar covers the battery and EV"
        o = self.brain.opts
        plan_hours = 4
        await self._set("number", "set_value", CONF_POWER, value=float(kw or o[CONF_TOPUP_KW]))
        await self._set("number", "set_value", CONF_DURATION, value=plan_hours * 60)
        await self._set("number", "set_value", CONF_CHARGE_TARGET, value=float(target or 100))
        ok = await self._set(
            "select", "select_option", CONF_MODE, option="Force Charge"
        )
        if ok:
            await self.brain.speaker.push(
                f"Grid top-up started: solar short by {short} kWh."
                if short is not None
                else "Grid top-up started."
            )
        if ok:
            self.brain.record("energy_actions")
            self.brain.log("energy", "battery action started")
        return "started" if ok else "failed"

    async def start_export(
        self, force: bool = False, kw: float | None = None, floor: float | None = None
    ) -> str:
        """Discharge to the grid during the evening feed-in window."""
        o = self.brain.opts
        soc = self._num(CONF_SOC)
        if not force and (soc is None or soc <= float(o[CONF_EXPORT_MIN_SOC])):
            return "skipped: battery too low to export"
        plan = self.plan()
        await self._set("number", "set_value", CONF_POWER, value=float(kw or o[CONF_EXPORT_KW]))
        await self._set("number", "set_value", CONF_DURATION, value=240)
        await self._set(
            "number", "set_value", CONF_DISCHARGE_TARGET, value=float(floor or o[CONF_EXPORT_FLOOR])
        )
        ok = await self._set(
            "select", "select_option", CONF_MODE, option="Force Discharge"
        )
        if ok:
            await self.brain.speaker.push(
                f"Evening export started at {plan.fit_evening:g}c/kWh."
            )
        if ok:
            self.brain.record("energy_actions")
            self.brain.log("energy", "battery action started")
        return "started" if ok else "failed"

    async def stop(self, only_mode: str | None = None) -> str:
        """Stop forced dispatch (optionally only when currently in ``only_mode``)."""
        mode_id = self.brain.opts.get(CONF_MODE)
        state = self.hass.states.get(mode_id) if mode_id else None
        if only_mode and (state is None or state.state != only_mode):
            return "skipped: not in that mode"
        await self._set("button", "press", CONF_STOP)
        await self._set("select", "select_option", CONF_MODE, option="Normal")
        return "stopped"

    async def ev_plugged_in(self, window: tuple[int, int]) -> str:
        """Gate EV charging to the cheap window."""
        now = dt_util.now()
        o = self.brain.opts
        soc, target = self._num(CONF_EV_SOC), self._num(CONF_EV_TARGET)
        start, end = window
        in_window = start <= now.hour < end and now < now.replace(
            hour=end, minute=0, second=0, microsecond=0
        ) - timedelta(minutes=15)
        if in_window and (soc is None or target is None or soc < target):
            if o.get(CONF_EV_START):
                await self._set("button", "press", CONF_EV_START)
            return "charging"
        await self.brain.speaker.say(
            f"The car is plugged in outside the {start}:00 to {end}:00 cheap window. "
            "Charging will wait.",
        )
        return "held"
