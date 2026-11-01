"""Config and options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from .const import *  # noqa: F403 - option keys
from .const import DEFAULTS, DOMAIN


def _entity(*domains: str, multiple: bool = False) -> sel.EntitySelector:
    return sel.EntitySelector(sel.EntitySelectorConfig(domain=list(domains), multiple=multiple))


def _num(low: float, high: float, step: float = 0.1, unit: str | None = None) -> sel.NumberSelector:
    return sel.NumberSelector(
        sel.NumberSelectorConfig(min=low, max=high, step=step, unit_of_measurement=unit, mode=sel.NumberSelectorMode.BOX)
    )


# Each section: key -> selector. Optional entity keys can be cleared.
SECTIONS: dict[str, dict[str, Any]] = {
    "general": {
        CONF_SPEAKERS: _entity("assist_satellite", "media_player", multiple=True),
        CONF_TTS_ENGINE: _entity("tts"),
        CONF_NOTIFY: _entity("notify"),
        CONF_MOTION: _entity("binary_sensor", multiple=True),
        CONF_AGENT: sel.ConversationAgentSelector(),
        CONF_QUIET_START: sel.TimeSelector(),
        CONF_QUIET_END: sel.TimeSelector(),
        CONF_BANNED: sel.TextSelector(),
        CONF_DEDUPE: _num(0, 240, 1, "min"),
    },
    "briefing": {
        CONF_BRIEF_MORNING: sel.TimeSelector(),
        CONF_BRIEF_EVENING: sel.TimeSelector(),
        CONF_BRIEF_SECTIONS: sel.SelectSelector(
            sel.SelectSelectorConfig(options=BRIEF_SECTIONS, multiple=True, mode=sel.SelectSelectorMode.LIST, translation_key="briefing_sections")
        ),
        CONF_BRIEF_AI: sel.BooleanSelector(),
        CONF_WEATHER: _entity("weather"),
        CONF_WEEKLY_TIME: sel.TimeSelector(),
        CONF_AUTO_BACKUP: sel.BooleanSelector(),
    },
    "house": {
        CONF_AI_TASK: _entity("ai_task"),
        CONF_AI_PER_HOUR: _num(0, 120, 1, "calls/h"),
        CONF_NIGHT_WATCH: sel.BooleanSelector(),
        CONF_NIGHT_START: sel.TimeSelector(),
        CONF_NIGHT_END: sel.TimeSelector(),
        CONF_DOORBELL: _entity("binary_sensor", "event", multiple=True),
        CONF_DOORBELL_CAMERA: _entity("camera"),
        CONF_LEARN: _entity("light", "switch", "lock", "cover", "binary_sensor", multiple=True),
    },
    "autopilot": {
        CONF_AP_MODE: sel.SelectSelector(
            sel.SelectSelectorConfig(options=AP_MODES, mode=sel.SelectSelectorMode.LIST, translation_key="autopilot_mode")
        ),
        CONF_AP_LLM: sel.BooleanSelector(),
        CONF_AP_NIGHT: _num(0.1, 0.7, 0.01, "of daily use"),
        CONF_AP_TIMEOUT: _num(10, 600, 5, "s"),
        CONF_AGENT: sel.ConversationAgentSelector(),
        CONF_AI_PER_HOUR: _num(0, 120, 1, "calls/h"),
    },
    "studio": {
        CONF_ST_PV: _entity("sensor"),
        CONF_ST_GRID: _entity("sensor"),
        CONF_ST_GRID_INVERT: sel.BooleanSelector(),
        CONF_ST_BATT: _entity("sensor"),
        CONF_ST_BATT_INVERT: sel.BooleanSelector(),
        CONF_ST_EV: _entity("sensor"),
        CONF_ST_DAY_PV: _entity("sensor"),
        CONF_ST_DAY_LOAD: _entity("sensor"),
        CONF_ST_DAY_EXPORT: _entity("sensor"),
        CONF_ST_DAY_IMPORT: _entity("sensor"),
    },
    "energy": {
        CONF_SOC: _entity("sensor"),
        CONF_MODE: _entity("select"),
        CONF_POWER: _entity("number"),
        CONF_DURATION: _entity("number"),
        CONF_CHARGE_TARGET: _entity("number"),
        CONF_DISCHARGE_TARGET: _entity("number"),
        CONF_STOP: _entity("button"),
        CONF_PV_TODAY: _entity("sensor"),
        CONF_PV_TOMORROW: _entity("sensor"),
        CONF_EV_SOC: _entity("sensor"),
        CONF_EV_PLUG: _entity("binary_sensor"),
        CONF_EV_TARGET: _entity("input_number", "number"),
        CONF_EV_START: _entity("button"),
        CONF_HOLIDAYS: _entity("calendar"),
        CONF_BATTERY_KWH: _num(1, 500, 0.1, "kWh"),
        CONF_EV_KWH: _num(1, 300, 0.1, "kWh"),
        CONF_RESERVE: _num(0, 100, 1, "%"),
        CONF_LOW_SOLAR: _num(0, 200, 1, "kWh"),
        CONF_TOPUP_KW: _num(0.5, 30, 0.1, "kW"),
        CONF_EXPORT_KW: _num(0.5, 30, 0.1, "kW"),
        CONF_EXPORT_MIN_SOC: _num(0, 100, 1, "%"),
        CONF_EXPORT_FLOOR: _num(0, 100, 1, "%"),
        CONF_AUTO_TOPUP: sel.BooleanSelector(),
        CONF_AUTO_EXPORT: sel.BooleanSelector(),
        CONF_EV_GATE: sel.BooleanSelector(),
    },
    "tariff": {
        CONF_RATE_SHOULDER: _num(0, 200, 0.001, "c/kWh"),
        CONF_RATE_OFF_PEAK: _num(0, 200, 0.001, "c/kWh"),
        CONF_RATE_HIGH_PEAK: _num(0, 200, 0.001, "c/kWh"),
        CONF_RATE_LOW_PEAK: _num(0, 200, 0.001, "c/kWh"),
        CONF_SUPPLY: _num(0, 1000, 0.001, "c/day"),
        CONF_FIT_EVENING: _num(0, 200, 0.001, "c/kWh"),
        CONF_FIT_MORNING: _num(0, 200, 0.001, "c/kWh"),
        CONF_FIT_OTHER: _num(0, 200, 0.001, "c/kWh"),
    },
}
CLEARABLE = {
    CONF_TTS_ENGINE, CONF_NOTIFY, CONF_AGENT, CONF_MODE, CONF_POWER, CONF_DURATION,
    CONF_CHARGE_TARGET, CONF_DISCHARGE_TARGET, CONF_STOP, CONF_PV_TODAY, CONF_PV_TOMORROW,
    CONF_EV_SOC, CONF_EV_PLUG, CONF_EV_TARGET, CONF_EV_START, CONF_HOLIDAYS, CONF_SOC,
    CONF_BRIEF_MORNING, CONF_BRIEF_EVENING, CONF_WEATHER, CONF_WEEKLY_TIME,
    CONF_AI_TASK, CONF_DOORBELL_CAMERA, CONF_ST_PV, CONF_ST_GRID, CONF_ST_BATT, CONF_ST_EV,
    CONF_ST_DAY_PV, CONF_ST_DAY_LOAD, CONF_ST_DAY_EXPORT, CONF_ST_DAY_IMPORT,
}


def section_schema(section: str, current: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    for key, selector in SECTIONS[section].items():
        value = current.get(key, DEFAULTS.get(key))
        marker = vol.Optional(key, description={"suggested_value": value})
        fields[marker] = selector
    return vol.Schema(fields)


def clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Drop blank optional entity ids so a cleared field really clears."""
    out = dict(user_input)
    for key in CLEARABLE:
        if key in out and not out[key]:
            out[key] = ""
    return out


class CortexConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data={}, options=DEFAULTS)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default="Cortex"): str}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return CortexOptionsFlow()


class CortexOptionsFlow(OptionsFlow):
    def _current(self) -> dict[str, Any]:
        return {**DEFAULTS, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["general", "briefing", "house", "autopilot", "studio", "energy", "tariff"])

    async def _section(self, section: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self._current(), **clean(user_input)})
        return self.async_show_form(
            step_id=section, data_schema=section_schema(section, self._current())
        )

    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("general", user_input)

    async def async_step_briefing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("briefing", user_input)

    async def async_step_house(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("house", user_input)

    async def async_step_autopilot(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("autopilot", user_input)

    async def async_step_studio(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("studio", user_input)

    async def async_step_energy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("energy", user_input)

    async def async_step_tariff(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("tariff", user_input)
