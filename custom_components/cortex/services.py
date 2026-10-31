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
)


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
        }), R),
        ("unwatch", unwatch, vol.Schema({vol.Required("id"): cv.string}), S),
        ("briefing", briefing, vol.Schema({vol.Optional("speak", default=True): cv.boolean}), R),
        ("hush", hush, vol.Schema({vol.Optional("minutes", default=60): vol.All(int, vol.Range(min=0))}), S),
        ("run_checks", run_checks, vol.Schema({}), R),
        ("energy_action", energy_action, vol.Schema({
            vol.Required("action"): vol.In(["topup", "export", "stop"]),
            vol.Optional("force", default=False): cv.boolean,
        }), R),
    ]
    for name, handler, schema, support in table:
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=support)


def async_unregister_services(hass: HomeAssistant) -> None:
    for name in SERVICES:
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)
