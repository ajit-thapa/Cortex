"""Cortex services."""

from __future__ import annotations

from datetime import timedelta

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import CONF_AGENT, DOMAIN
from .memory import CATEGORIES
from .runtime import Cortex

SERVICES = (
    "say", "ask", "remember", "recall", "forget", "remind", "cancel_reminder",
    "watch", "unwatch", "briefing", "hush", "run_checks", "energy_action",
    "save_routine", "delete_routine", "run_routine", "accept_suggestion",
    "dismiss_suggestion", "add_motion_light", "remove_motion_light", "add_heating",
    "remove_heating", "security_check", "look", "set_spot", "parcels_collected",
    "weekly_report", "backup", "restore",
)


def _fields(data, *keys):
    return {k: data[k] for k in keys if k in data}


def _brain(hass: HomeAssistant) -> Cortex:
    for value in hass.data.get(DOMAIN, {}).values():
        if isinstance(value, Cortex):
            return value
    raise HomeAssistantError("Cortex is not set up")


def async_register_services(hass: HomeAssistant) -> None:
    async def say(call: ServiceCall) -> ServiceResponse:
        return await _brain(hass).speaker.say(
            call.data["message"], call.data["urgent"], call.data.get("area")
        )

    async def ask(call: ServiceCall) -> ServiceResponse:
        brain = _brain(hass)
        data = {"text": call.data["question"]}
        agent = call.data.get("agent_id") or brain.opts.get(CONF_AGENT)
        if agent:
            data["agent_id"] = agent
        result = await hass.services.async_call(
            "conversation", "process", data, blocking=True, return_response=True
        )
        answer = (
            (result or {}).get("response", {}).get("speech", {}).get("plain", {}).get("speech", "")
        )
        if call.data["speak"] and answer:
            await brain.speaker.say(answer)
        return {"answer": answer}

    async def remember(call: ServiceCall) -> ServiceResponse:
        memory = _brain(hass).remember(
            call.data["text"], call.data["category"], call.data.get("source")
        )
        return {"id": memory.id, "text": memory.text}

    async def recall(call: ServiceCall) -> ServiceResponse:
        found = _brain(hass).book.recall(call.data.get("query", ""), call.data["limit"])
        return {"memories": [{"id": m.id, "text": m.text, "category": m.category} for m in found]}

    async def forget(call: ServiceCall) -> ServiceResponse:
        memory = _brain(hass).forget(call.data["memory"])
        return {"forgotten": memory.text if memory else None}

    async def remind(call: ServiceCall) -> ServiceResponse:
        when = call.data.get("at") or (dt_util.now() + timedelta(minutes=call.data["in_minutes"]))
        item = _brain(hass).add_reminder(call.data["message"], dt_util.as_local(when))
        return {"id": item["id"], "at": item["at"]}

    async def cancel_reminder(call: ServiceCall) -> None:
        if not _brain(hass).cancel_reminder(call.data["id"]):
            raise HomeAssistantError("No such reminder")

    async def watch(call: ServiceCall) -> ServiceResponse:
        item = _brain(hass).add_watch(
            call.data["entity_id"],
            call.data["message"],
            call.data.get("to_state"),
            call.data["cooldown"],
            call.data["urgent"],
            call.data["ai"],
            call.data.get("camera"),
        )
        return {"id": item["id"]}

    async def unwatch(call: ServiceCall) -> None:
        if not _brain(hass).remove_watch(call.data["id"]):
            raise HomeAssistantError("No such watch")

    async def briefing(call: ServiceCall) -> ServiceResponse:
        brain = _brain(hass)
        text = brain.briefing_text()
        if call.data["speak"]:
            await brain.speaker.say(text)
        return {"text": text}

    async def hush(call: ServiceCall) -> None:
        minutes = call.data["minutes"]
        _brain(hass).gate.hush(dt_util.now() + timedelta(minutes=minutes) if minutes else None)
        _brain(hass).notify_update()

    async def run_checks(call: ServiceCall) -> ServiceResponse:
        return {"issues": await _brain(hass).run_health()}

    async def energy_action(call: ServiceCall) -> ServiceResponse:
        brain = _brain(hass)
        action = call.data["action"]
        if action == "topup":
            result = await brain.energy.start_topup(call.data["force"])
        elif action == "export":
            result = await brain.energy.start_export(call.data["force"])
        else:
            result = await brain.energy.stop()
        brain.refresh()
        return {"result": result}

    def _wrap(fn):
        try:
            return fn()
        except (vol.Invalid, ValueError) as err:
            raise HomeAssistantError(str(err)) from err

    async def save_routine(call: ServiceCall) -> ServiceResponse:
        d = _fields(call.data, "name", "steps", "schedule", "on_state", "enabled")
        return {"routine": _wrap(lambda: _brain(hass).routines.save(d))}

    async def delete_routine(call: ServiceCall) -> None:
        if not _brain(hass).routines.delete(call.data["name"]):
            raise HomeAssistantError("No such routine")

    async def run_routine(call: ServiceCall) -> ServiceResponse:
        return {"results": await _brain(hass).routines.run(call.data["name"])}

    async def accept_suggestion(call: ServiceCall) -> ServiceResponse:
        return {"routine": _wrap(lambda: _brain(hass).learning.accept(call.data["id"]))}

    async def dismiss_suggestion(call: ServiceCall) -> None:
        if not _brain(hass).learning.dismiss(call.data["id"]):
            raise HomeAssistantError("No such suggestion")

    async def add_motion_light(call: ServiceCall) -> ServiceResponse:
        d = _fields(call.data, "name", "motion", "lights", "delay", "brightness", "only_dark", "lux_sensor", "lux_below")
        return {"rule": _wrap(lambda: _brain(hass).motion_lights.save(d))}

    async def remove_motion_light(call: ServiceCall) -> None:
        if not _brain(hass).motion_lights.delete(call.data["name"]):
            raise HomeAssistantError("No such motion light")

    async def add_heating(call: ServiceCall) -> ServiceResponse:
        d = _fields(call.data, "name", "climate", "target", "ready_by", "days", "hvac_mode", "persons", "rate")
        return {"rule": _wrap(lambda: _brain(hass).heating.save(d))}

    async def remove_heating(call: ServiceCall) -> None:
        if not _brain(hass).heating.delete(call.data["name"]):
            raise HomeAssistantError("No such heating rule")

    async def security_check(call: ServiceCall) -> ServiceResponse:
        brain = _brain(hass)
        result = brain.security.check()
        if call.data["speak"]:
            await brain.speaker.say(result["text"])
        return result

    async def look(call: ServiceCall) -> ServiceResponse:
        brain = _brain(hass)
        text = await brain.look(call.data["camera"], call.data.get("question"))
        if call.data["speak"] and text:
            await brain.speaker.say(text)
        return {"answer": text}

    async def set_spot(call: ServiceCall) -> None:
        _brain(hass).visitors.set_spot(call.data["camera"], call.data["spot"])

    async def parcels_collected(call: ServiceCall) -> None:
        _brain(hass).visitors.collected()

    async def weekly_report(call: ServiceCall) -> ServiceResponse:
        brain = _brain(hass)
        if call.data["speak"]:
            return {"text": await brain.briefing.weekly_report()}
        return {"text": brain.briefing.weekly_text()}

    async def backup(call: ServiceCall) -> ServiceResponse:
        return {"path": await _brain(hass).backup.create()}

    async def restore(call: ServiceCall) -> ServiceResponse:
        brain = _brain(hass)
        name = await brain.backup.restore(call.data.get("file"), call.data["with_options"])
        return {"restored": name}

    S, R = SupportsResponse.NONE, SupportsResponse.OPTIONAL
    table = [
        ("say", say, vol.Schema({
            vol.Required("message"): cv.string,
            vol.Optional("urgent", default=False): cv.boolean,
            vol.Optional("area"): cv.string,
        }), R),
        ("ask", ask, vol.Schema({
            vol.Required("question"): cv.string,
            vol.Optional("agent_id"): cv.string,
            vol.Optional("speak", default=False): cv.boolean,
        }), SupportsResponse.ONLY),
        ("remember", remember, vol.Schema({
            vol.Required("text"): cv.string,
            vol.Optional("category", default="fact"): vol.In(CATEGORIES),
            vol.Optional("source"): cv.string,
        }), R),
        ("recall", recall, vol.Schema({
            vol.Optional("query", default=""): cv.string,
            vol.Optional("limit", default=6): vol.All(int, vol.Range(min=1, max=30)),
        }), SupportsResponse.ONLY),
        ("forget", forget, vol.Schema({vol.Required("memory"): cv.string}), R),
        ("remind", remind, vol.Schema({
            vol.Required("message"): cv.string,
            vol.Optional("at"): cv.datetime,
            vol.Optional("in_minutes", default=30): vol.All(int, vol.Range(min=1, max=60 * 24 * 30)),
        }), R),
        ("cancel_reminder", cancel_reminder, vol.Schema({vol.Required("id"): cv.string}), S),
        ("watch", watch, vol.Schema({
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("message"): cv.string,
            vol.Optional("to_state"): cv.string,
            vol.Optional("cooldown", default=600): vol.All(int, vol.Range(min=0)),
            vol.Optional("urgent", default=False): cv.boolean,
            vol.Optional("ai", default=False): cv.boolean,
            vol.Optional("camera"): cv.entity_id,
        }), R),
        ("unwatch", unwatch, vol.Schema({vol.Required("id"): cv.string}), S),
        ("briefing", briefing, vol.Schema({vol.Optional("speak", default=True): cv.boolean}), R),
        ("hush", hush, vol.Schema({vol.Optional("minutes", default=60): vol.All(int, vol.Range(min=0))}), S),
        ("run_checks", run_checks, vol.Schema({}), R),
        ("energy_action", energy_action, vol.Schema({
            vol.Required("action"): vol.In(["topup", "export", "stop"]),
            vol.Optional("force", default=False): cv.boolean,
        }), R),
        ("save_routine", save_routine, vol.Schema({
            vol.Required("name"): cv.string,
            vol.Required("steps"): list,
            vol.Optional("schedule"): dict,
            vol.Optional("on_state"): dict,
            vol.Optional("enabled"): cv.boolean,
        }), SupportsResponse.OPTIONAL),
        ("delete_routine", delete_routine, vol.Schema({vol.Required("name"): cv.string}), S),
        ("run_routine", run_routine, vol.Schema({vol.Required("name"): cv.string}), SupportsResponse.OPTIONAL),
        ("accept_suggestion", accept_suggestion, vol.Schema({vol.Required("id"): cv.string}), SupportsResponse.OPTIONAL),
        ("dismiss_suggestion", dismiss_suggestion, vol.Schema({vol.Required("id"): cv.string}), S),
        ("add_motion_light", add_motion_light, vol.Schema({
            vol.Required("name"): cv.string,
            vol.Required("motion"): cv.entity_ids,
            vol.Required("lights"): cv.entity_ids,
            vol.Optional("delay"): vol.All(int, vol.Range(min=10, max=7200)),
            vol.Optional("brightness"): vol.All(int, vol.Range(min=1, max=100)),
            vol.Optional("only_dark"): cv.boolean,
            vol.Optional("lux_sensor"): cv.entity_id,
            vol.Optional("lux_below"): vol.Coerce(float),
        }), SupportsResponse.OPTIONAL),
        ("remove_motion_light", remove_motion_light, vol.Schema({vol.Required("name"): cv.string}), S),
        ("add_heating", add_heating, vol.Schema({
            vol.Required("name"): cv.string,
            vol.Required("climate"): cv.entity_id,
            vol.Required("target"): vol.Coerce(float),
            vol.Required("ready_by"): cv.string,
            vol.Optional("days"): vol.In(["daily", "weekdays", "weekends"]),
            vol.Optional("hvac_mode"): cv.string,
            vol.Optional("persons"): cv.entity_ids,
            vol.Optional("rate"): vol.Coerce(float),
        }), SupportsResponse.OPTIONAL),
        ("remove_heating", remove_heating, vol.Schema({vol.Required("name"): cv.string}), S),
        ("security_check", security_check, vol.Schema({vol.Optional("speak", default=False): cv.boolean}), SupportsResponse.OPTIONAL),
        ("look", look, vol.Schema({
            vol.Required("camera"): cv.entity_id,
            vol.Optional("question"): cv.string,
            vol.Optional("speak", default=False): cv.boolean,
        }), SupportsResponse.ONLY),
        ("set_spot", set_spot, vol.Schema({
            vol.Required("camera"): cv.entity_id,
            vol.Required("spot"): vol.Any(cv.string, None),
        }), S),
        ("parcels_collected", parcels_collected, vol.Schema({}), S),
        ("weekly_report", weekly_report, vol.Schema({vol.Optional("speak", default=False): cv.boolean}), SupportsResponse.OPTIONAL),
        ("backup", backup, vol.Schema({}), SupportsResponse.OPTIONAL),
        ("restore", restore, vol.Schema({
            vol.Optional("file"): cv.string,
            vol.Optional("with_options", default=False): cv.boolean,
        }), SupportsResponse.OPTIONAL),
    ]
    for name, handler, schema, support in table:
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=support)


def async_unregister_services(hass: HomeAssistant) -> None:
    for name in SERVICES:
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)
