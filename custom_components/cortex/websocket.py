"""WebSocket API for the sidebar panel."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .memory import CATEGORIES
from .runtime import Cortex
from . import tariff


def _brain(hass: HomeAssistant) -> Cortex | None:
    for value in hass.data.get(DOMAIN, {}).values():
        if isinstance(value, Cortex):
            return value
    return None


def _json_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    out = dict(snap)
    if "next_change" in out:
        out["next_change"] = out["next_change"].isoformat()
    return out


def async_register_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_overview)
    websocket_api.async_register_command(hass, ws_memory_add)
    websocket_api.async_register_command(hass, ws_memory_delete)
    websocket_api.async_register_command(hass, ws_hush)
    websocket_api.async_register_command(hass, ws_cancel)


@websocket_api.websocket_command({vol.Required("type"): "cortex/overview"})
@websocket_api.async_response
async def ws_overview(hass: HomeAssistant, connection, msg) -> None:
    brain = _brain(hass)
    if brain is None:
        connection.send_error(msg["id"], "not_loaded", "Cortex is not set up")
        return
    brain.refresh()
    now = dt_util.now()
    hushed = brain.gate.hushed_until
    connection.send_result(
        msg["id"],
        {
            "energy": _json_snapshot(brain.snapshot),
            "schedule": [
                {"hour": h, "import": i, "feed_in": f}
                for h, i, f in tariff.schedule(now.date(), brain.energy.plan(), brain.energy.is_holiday(now.date()))
            ],
            "hour": now.hour,
            "memories": [vars(m) for m in brain.book.items],
            "categories": list(CATEGORIES),
            "watches": brain.watches,
            "reminders": brain.reminders,
            "health": brain.health,
            "speech": list(brain.speaker.log),
            "hushed": bool(hushed and hushed > now),
            "automation": {
                "topup": brain.opts["auto_topup"],
                "export": brain.opts["auto_export"],
                "ev_gate": brain.opts["ev_gate"],
            },
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "cortex/memory_add",
        vol.Required("text"): str,
        vol.Optional("category", default="fact"): str,
    }
)
@websocket_api.async_response
async def ws_memory_add(hass: HomeAssistant, connection, msg) -> None:
    brain = _brain(hass)
    if brain is None:
        connection.send_error(msg["id"], "not_loaded", "Cortex is not set up")
        return
    memory = brain.remember(msg["text"], msg["category"], "panel")
    connection.send_result(msg["id"], vars(memory))


@websocket_api.websocket_command(
    {vol.Required("type"): "cortex/memory_delete", vol.Required("id"): str}
)
@websocket_api.async_response
async def ws_memory_delete(hass: HomeAssistant, connection, msg) -> None:
    brain = _brain(hass)
    gone = brain.forget(msg["id"]) if brain else None
    connection.send_result(msg["id"], {"deleted": bool(gone)})


@websocket_api.websocket_command(
    {vol.Required("type"): "cortex/hush", vol.Required("minutes"): vol.All(int, vol.Range(min=0))}
)
@websocket_api.async_response
async def ws_hush(hass: HomeAssistant, connection, msg) -> None:
    brain = _brain(hass)
    if brain:
        minutes = msg["minutes"]
        brain.gate.hush(dt_util.now() + timedelta(minutes=minutes) if minutes else None)
        brain.notify_update()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {vol.Required("type"): "cortex/cancel", vol.Required("kind"): vol.In(["reminder", "watch"]), vol.Required("id"): str}
)
@websocket_api.async_response
async def ws_cancel(hass: HomeAssistant, connection, msg) -> None:
    brain = _brain(hass)
    ok = False
    if brain:
        ok = brain.cancel_reminder(msg["id"]) if msg["kind"] == "reminder" else brain.remove_watch(msg["id"])
    connection.send_result(msg["id"], {"ok": ok})
