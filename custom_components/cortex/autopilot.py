"""Autopilot: ask the user's local model for the day's battery plan, bound it, act or advise."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from . import autopilot_rules as rules
from .const import (
    AP_MODES,
    CONF_AP_LLM,
    CONF_AP_MODE,
    CONF_AP_NIGHT,
    CONF_BATTERY_KWH,
    CONF_EV_KWH,
    CONF_EXPORT_FLOOR,
    CONF_EXPORT_KW,
    CONF_RATE_HIGH_PEAK,
    CONF_RATE_LOW_PEAK,
    CONF_ST_DAY_LOAD,
    CONF_TOPUP_KW,
)
from .feature import Feature

_LOGGER = logging.getLogger(__name__)
DEFAULT_LOAD = 22.0  # kWh/day when no history exists yet
KEEP = 40


class Autopilot(Feature):
    name = "autopilot"

    def __init__(self, brain) -> None:
        super().__init__(brain)
        self.decisions: list[dict[str, Any]] = []
        self.active: dict[str, Any] | None = None

    # ---- state ---------------------------------------------------------
    def load(self, data) -> None:
        data = data or {}
        self.decisions = data.get("decisions", [])
        self.active = data.get("active")

    def dump(self) -> dict[str, Any]:
        return {"decisions": self.decisions[-KEEP:], "active": self.active}

    @property
    def mode(self) -> str:
        mode = self.brain.opts.get(CONF_AP_MODE, "shadow")
        return mode if mode in AP_MODES else "off"

    @property
    def controls(self) -> bool:
        """True when Autopilot (not the plain timers) drives the battery."""
        return self.mode == "auto"

    @property
    def last(self) -> dict[str, Any] | None:
        return self.decisions[-1] if self.decisions else None

    # ---- schedule ------------------------------------------------------
    async def start(self) -> None:
        if self.mode == "off":
            return
        plan = self.brain.energy.plan()
        (s0, s1), (f0, f1) = plan.shoulder_window, plan.fit_evening_window

        async def decide_topup(_now: datetime) -> None:
            await self.decide(rules.TOPUP)

        async def decide_export(_now: datetime) -> None:
            await self.decide(rules.EXPORT)

        async def stop_topup(_now: datetime) -> None:
            await self.finish("Force Charge")

        async def stop_export(_now: datetime) -> None:
            await self.finish("Force Discharge")

        for fn, hour, sec in (
            (decide_topup, s0, 45), (decide_export, f0, 45), (stop_topup, s1, 15), (stop_export, f1 % 24, 15)
        ):
            self._unsubs.append(async_track_time_change(self.hass, fn, hour=hour, minute=0, second=sec))

    # ---- data ----------------------------------------------------------
    async def avg_daily_load(self) -> float:
        entity = self.brain.opts.get(CONF_ST_DAY_LOAD)
        if not entity:
            return DEFAULT_LOAD
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.statistics import statistics_during_period

            start = dt_util.utcnow() - timedelta(days=8)
            stats = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period, self.hass, start, None, {entity}, "day", None, {"max"}
            )
            values = [r["max"] for r in stats.get(entity, []) if r.get("max")]
            values = values[-7:]
            if len(values) >= 3:
                return round(sum(values) / len(values), 1)
        except Exception as err:  # noqa: BLE001 - history is a nicety, never a blocker
            _LOGGER.debug("No load history: %s", err)
        return DEFAULT_LOAD

    async def context(self) -> dict[str, Any]:
        brain, o = self.brain, self.brain.opts
        brain.refresh()
        s, plan = brain.snapshot, brain.energy.plan()
        ev_need = 0.0
        if s.get("ev_room") is not None:
            ev_need = float(s["ev_room"])
        recent = [
            {"window": d["window"], "do": d["do"], "reason": d.get("reason", "")[:80], "result": d.get("result")}
            for d in self.decisions[-4:]
        ]
        return {
            "now": dt_util.now().strftime("%a %H:%M"),
            "soc": s.get("battery_soc"),
            "battery_kwh": float(o[CONF_BATTERY_KWH]),
            "pv_today": s.get("pv_today"),
            "pv_tomorrow": s.get("pv_tomorrow"),
            "avg_daily_load": await self.avg_daily_load(),
            "night_share": float(o[CONF_AP_NIGHT]),
            "ev_plugged": bool(s.get("ev_plugged")),
            "ev_need_kwh": round(ev_need, 1),
            "shoulder": plan.shoulder,
            "off_peak": plan.off_peak,
            "peak": float(o[CONF_RATE_HIGH_PEAK] if s.get("high_season") else o[CONF_RATE_LOW_PEAK]),
            "fit_evening": plan.fit_evening,
            "feed_in_now": s.get("feed_in_rate", 0.0),
            "business_day": bool(s.get("business_day")),
            "topup_kw": float(o[CONF_TOPUP_KW]),
            "export_kw": float(o[CONF_EXPORT_KW]),
            "export_floor": float(o[CONF_EXPORT_FLOOR]),
            "ev_kwh": float(o[CONF_EV_KWH]),
            "recent": recent,
        }

    # ---- decide / act --------------------------------------------------
    async def decide(self, window: str, execute: bool | None = None) -> dict[str, Any]:
        """Plan one window. ``execute`` defaults to True only in auto mode."""
        brain = self.brain
        ctx = await self.context()
        base = rules.baseline(window, ctx)
        raw = None
        if brain.opts.get(CONF_AP_LLM) and brain.ai_allowed():
            try:
                raw = rules.parse(await brain.ask_agent(rules.prompt(window, ctx, base)))
            except HomeAssistantError as err:
                _LOGGER.warning("Autopilot model call failed: %s", err)
        decision = rules.validate(window, raw, ctx, base)
        decision["time"] = dt_util.now().isoformat(timespec="seconds")
        decision["soc"] = ctx.get("soc")
        decision["mode"] = self.mode
        run = (self.mode == "auto") if execute is None else execute
        decision["result"] = "advice"
        if run and decision["do"]:
            decision["result"] = await self._act(decision)
        elif run:
            decision["result"] = "no action"
        self.decisions.append(decision)
        text = rules.describe(decision)
        brain.log("autopilot", f"[{decision['source']}/{decision['result']}] {text}")
        brain.record("autopilot_decisions")
        brain.save()
        if decision["do"] or window == rules.TOPUP:
            prefix = "Autopilot" if decision["result"] in ("started", "failed") else "Autopilot advice"
            await brain.speaker.push(f"{prefix}: {text}", title="Cortex autopilot")
        return decision

    async def _act(self, d: dict[str, Any]) -> str:
        energy, cap = self.brain.energy, float(self.brain.opts[CONF_BATTERY_KWH])
        if d["window"] == rules.TOPUP:
            result = await energy.start_topup(True, d["kw"], d["target_soc"])
            mode = "Force Charge"
        else:
            result = await energy.start_export(True, d["kw"], d["floor_soc"])
            mode = "Force Discharge"
        if result == "started":
            self.active = {"mode": mode, "soc0": d.get("soc"), "cap": cap, "window": d["window"], "at": d["time"]}
        return result

    async def finish(self, mode: str) -> None:
        """End a dispatch Autopilot started and book what it achieved."""
        active = self.active
        if not active or active["mode"] != mode:
            return
        await self.brain.energy.stop(mode)
        self.brain.refresh()
        soc1 = self.brain.snapshot.get("battery_soc")
        soc0 = active.get("soc0")
        self.active = None
        if soc1 is None or soc0 is None:
            self.brain.save()
            return
        kwh = abs(soc1 - soc0) / 100 * active["cap"]
        plan = self.brain.energy.plan()
        cents = kwh * (plan.fit_evening * 0.9 if active["window"] == rules.EXPORT else -plan.shoulder)
        outcome = f"{active['window']}: {soc0:.0f}% to {soc1:.0f}% ({kwh:.1f} kWh, {cents / 100:+.2f} dollars)"
        for d in reversed(self.decisions):
            if d["window"] == active["window"] and d.get("result") == "started":
                d["outcome"] = outcome
                break
        self.brain.log("autopilot", f"Finished {outcome}")
        self.brain.record("autopilot_cents", cents)
        self.brain.save()
