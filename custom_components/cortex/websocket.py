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
    websocket_api.async_register_command(hass, ws_action)


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
            "routines": list(brain.routines.items.values()),
            "motion_lights": list(brain.motion_lights.rules.values()),
            "heating": list(brain.heating.rules.values()),
            "suggestions": [x for x in brain.learning.suggestions if x["status"] == "new"],
            "visitors": {
                "log": brain.visitors.log[-15:][::-1],
                "parcels": brain.visitors.parcels_waiting,
                "today": brain.visitors.today_count(),
                "spots": brain.visitors.spots,
                "cameras": sorted(s.entity_id for s in hass.states.async_all("camera")),
            },
            "timeline": list(brain.timeline.items)[:30],
            "week": brain.timeline.week(),
            "security": brain.security.check(),
            "backups": await brain.backup.list(),
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


ACTIONS = (
    "accept_suggestion", "dismiss_suggestion", "run_routine", "delete_routine",
    "set_spot", "parcels_collected", "security_check", "backup", "weekly_report",
)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "cortex/action",
        vol.Required("action"): vol.In(ACTIONS),
        vol.Optional("id"): str,
        vol.Optional("camera"): str,
        vol.Optional("spot"): str,
    }
)
@websocket_api.async_response
async def ws_action(hass: HomeAssistant, connection, msg) -> None:
    brain = _brain(hass)
    if brain is None:
        connection.send_error(msg["id"], "not_loaded", "Cortex is not set up")
        return
    action, ident = msg["action"], msg.get("id", "")
    try:
        if action == "accept_suggestion":
            result: Any = brain.learning.accept(ident)
        elif action == "dismiss_suggestion":
            result = brain.learning.dismiss(ident)
        elif action == "run_routine":
            result = await brain.routines.run(ident)
        elif action == "delete_routine":
            result = brain.routines.delete(ident)
        elif action == "set_spot":
            brain.visitors.set_spot(msg.get("camera", ""), msg.get("spot", ""))
            result = True
        elif action == "parcels_collected":
            brain.visitors.collected()
            result = True
        elif action == "security_check":
            result = brain.security.check()
        elif action == "backup":
            result = await brain.backup.create()
        else:
            result = await brain.briefing.weekly_report()
    except Exception as err:  # noqa: BLE001 - report to the panel instead of a stack trace
        connection.send_error(msg["id"], "failed", str(err))
        return
    connection.send_result(msg["id"], {"result": result})
