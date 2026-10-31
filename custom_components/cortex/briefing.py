"""Scheduled, configurable briefings and the weekly report."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    BRIEF_SECTIONS,
    CONF_AUTO_BACKUP,
    CONF_BRIEF_AI,
    CONF_BRIEF_EVENING,
    CONF_BRIEF_MORNING,
    CONF_BRIEF_SECTIONS,
    CONF_WEATHER,
    CONF_WEEKLY_TIME,
)
from .feature import Feature

_LOGGER = logging.getLogger(__name__)


def _hm(value) -> tuple[int, int] | None:
    if not value:
        return None
    parts = str(value).split(":")
    return int(parts[0]), int(parts[1])


class Briefing(Feature):
    name = "briefing"

    async def start(self) -> None:
        o = self.brain.opts
        for key, kind in ((CONF_BRIEF_MORNING, "morning"), (CONF_BRIEF_EVENING, "evening")):
            at = _hm(o.get(key))
            if at:

                async def fire(_now: datetime, kind=kind) -> None:
                    await self.deliver(kind)

                self._unsubs.append(
                    async_track_time_change(self.hass, fire, hour=at[0], minute=at[1], second=0)
                )
        weekly = _hm(o.get(CONF_WEEKLY_TIME))
        if weekly:

            async def week(now: datetime) -> None:
                if dt_util.as_local(now).weekday() == 6:  # Sunday
                    await self.weekly_report()

            self._unsubs.append(
                async_track_time_change(self.hass, week, hour=weekly[0], minute=weekly[1], second=30)
            )

    # ---- daily briefing -------------------------------------------------
    def build(self, sections: list[str] | None = None, kind: str | None = None) -> str:
        brain = self.brain
        brain.refresh()
        snap, now = brain.snapshot, dt_util.now()
        sections = sections if sections is not None else list(
            brain.opts.get(CONF_BRIEF_SECTIONS) or BRIEF_SECTIONS
        )
        kind = kind or ("morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening")
        parts = [f"Good {kind}."]
        if "weather" in sections:
            weather = self._weather()
            if weather:
                parts.append(weather)
        if "energy" in sections:
            parts.extend(self._energy(snap))
        if "reminders" in sections:
            today = [
                r["message"]
                for r in brain.reminders
                if (dt_util.parse_datetime(r["at"]) or now).date() == now.date()
            ]
            if today:
                parts.append("Reminders today: " + "; ".join(today) + ".")
        if "parcels" in sections:
            waiting = brain.visitors.parcels_waiting
            if waiting:
                parts.append(f"{waiting} parcel{'s' if waiting != 1 else ''} may be waiting at the door.")
        if "security" in sections:
            check = brain.security.check()
            if not check["ok"]:
                parts.append(check["text"])
        if "health" in sections and brain.health:
            parts.append(f"{len(brain.health)} thing{'s' if len(brain.health) != 1 else ''} need attention in the house.")
        return " ".join(parts)

    def _weather(self) -> str | None:
        entity = self.brain.opts.get(CONF_WEATHER)
        state = self.hass.states.get(entity) if entity else None
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        temp = state.attributes.get("temperature")
        unit = state.attributes.get("temperature_unit", "")
        out = f"It is {state.state.replace('-', ' ')}"
        return out + (f" and {temp:g} degrees." if isinstance(temp, (int, float)) else ".") if unit or temp else out + "."

    @staticmethod
    def _energy(snap: dict) -> list[str]:
        out = [
            f"Power is {snap['period'].replace('_', ' ')} at {snap['import_rate']:g} cents, changing to "
            f"{snap['next_period'].replace('_', ' ')} at {snap['next_change'].astimezone().strftime('%-I:%M %p')}."
        ]
        if snap["pv_today"] is not None:
            out.append(f"Solar forecast is {snap['pv_today']:.0f} kilowatt hours, a {snap['solar_day']} day.")
        if snap["battery_soc"] is not None:
            out.append(f"The battery is at {snap['battery_soc']:.0f} percent.")
        if snap["pv_shortfall"] is not None and snap["pv_shortfall"] > 0:
            out.append(
                f"Solar is short by {snap['pv_shortfall']:.0f} kilowatt hours, so a grid top-up is likely."
            )
        return out

    async def deliver(self, kind: str = "morning") -> str:
        text = self.build(kind=kind)
        if self.brain.opts.get(CONF_BRIEF_AI):
            text = await self._polish(text)
        await self.brain.speaker.say(text)
        self.brain.log("briefing", f"{kind} briefing")
        return text

    async def _polish(self, text: str) -> str:
        if not self.brain.ai_allowed():
            return text
        try:
            reply = await self.brain.ask_agent(
                "Rewrite this household briefing as a warm, natural spoken update of at most "
                "four sentences. Keep every fact and number. No markdown.\n\n" + text
            )
        except HomeAssistantError:
            return text
        return reply or text

    # ---- weekly report --------------------------------------------------
    def weekly_text(self) -> str:
        brain = self.brain
        w = brain.timeline.week()
        n = lambda k: int(w.get(k, 0))  # noqa: E731
        parts = ["Week in review."]
        parts.append(
            f"I spoke {n('spoken')} time{'s' if n('spoken') != 1 else ''}"
            + (f" and held back {n('suppressed')}" if n("suppressed") else "")
            + "."
        )
        for key, label in (
            ("alerts", "safety alert"),
            ("visitors", "visitor"),
            ("parcels", "parcel"),
            ("routines_run", "routine run"),
            ("reminders", "reminder"),
            ("energy_actions", "battery action"),
        ):
            if n(key):
                parts.append(f"{n(key)} {label}{'s' if n(key) != 1 else ''}.")
        if "pv_forecast" in w:
            parts.append(f"Solar forecast averaged {w['pv_forecast']:g} kilowatt hours a day.")
        if "soc_min" in w and "soc_max" in w:
            parts.append(f"Battery ranged from {w['soc_min']:.0f} to {w['soc_max']:.0f} percent.")
        if n("suggestions"):
            parts.append(f"I found {n('suggestions')} routine suggestion{'s' if n('suggestions') != 1 else ''} for you to review.")
        if brain.health:
            parts.append(f"{len(brain.health)} house health issue{'s' if len(brain.health) != 1 else ''} still open.")
        return " ".join(parts)

    async def weekly_report(self) -> str:
        text = self.weekly_text()
        await self.brain.speaker.say(text, push=True)
        self.brain.log("report", "Weekly report")
        if self.brain.opts.get(CONF_AUTO_BACKUP):
            try:
                await self.brain.backup.create()
            except OSError as err:
                _LOGGER.warning("Weekly backup failed: %s", err)
        return text
