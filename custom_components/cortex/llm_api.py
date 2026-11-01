"""Expose the shared brain to any conversation agent as an LLM API."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .memory import CATEGORIES
from .runtime import Cortex

PROMPT = (
    "You share a household memory with every other assistant in the house. "
    "Use cortex tools to remember durable facts the user tells you, recall them "
    "before answering questions about the household, and set reminders. "
    "Energy questions: use energy_status instead of guessing; for why the battery did something, use autopilot_status. "
    "For house questions (doors, visitors, parcels, what happened today) use house_status or timeline. "
    "Answer briefly and in plain words, then say what you did if you changed anything. "
    "Never invent numbers: if a tool has no value, say so."
)


def _out(data: dict[str, Any]) -> Any:
    """Wrap tool output in ToolResult where this Home Assistant has it."""
    result = getattr(llm, "ToolResult", None)
    return result(data=data) if result else data


class _Tool(llm.Tool):
    integration = DOMAIN  # required for custom tools from HA 2027.10

    def __init__(self, brain: Cortex) -> None:
        self.brain = brain


class RememberTool(_Tool):
    name = "remember"
    description = "Save a short durable fact about the household or its people."
    parameters = vol.Schema(
        {
            vol.Required("text"): str,
            vol.Optional("category", default="fact"): vol.In(CATEGORIES),
        }
    )

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> dict[str, Any]:
        args = tool_input.tool_args
        memory = self.brain.remember(args["text"], args.get("category", "fact"), "llm")
        return _out({"saved": memory.text, "id": memory.id})


class RecallTool(_Tool):
    name = "recall"
    description = "Search shared household memory."
    parameters = vol.Schema({vol.Optional("query", default=""): str})

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        found = self.brain.book.recall(tool_input.tool_args.get("query", ""))
        return _out({"memories": [m.text for m in found]})


class ForgetTool(_Tool):
    name = "forget"
    description = "Remove a memory by id or by describing it."
    parameters = vol.Schema({vol.Required("memory"): str})

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        gone = self.brain.forget(tool_input.tool_args["memory"])
        return _out({"forgotten": gone.text if gone else None})


class RemindTool(_Tool):
    name = "remind"
    description = (
        "Speak a reminder aloud. Give in_minutes for a delay, or at as a 24 hour HH:MM clock time "
        "(today, or tomorrow if that time has passed)."
    )
    parameters = vol.Schema(
        {
            vol.Required("message"): str,
            vol.Optional("in_minutes"): vol.All(int, vol.Range(min=1, max=60 * 24 * 14)),
            vol.Optional("at"): vol.Match(r"^([01]?\d|2[0-3]):[0-5]\d$"),
        }
    )

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        args = tool_input.tool_args
        from datetime import timedelta

        now = dt_util.now()
        if args.get("at"):
            hh, mm = (int(x) for x in args["at"].split(":"))
            when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if when <= now:
                when += timedelta(days=1)
        elif args.get("in_minutes"):
            when = now + timedelta(minutes=args["in_minutes"])
        else:
            return _out({"error": "give in_minutes or at"})
        item = self.brain.add_reminder(args["message"], when)
        return _out({"reminder": item["id"], "at": item["at"]})


class RemindersTool(_Tool):
    name = "reminders"
    description = "List pending reminders, or cancel one by id."
    parameters = vol.Schema({vol.Optional("cancel"): str})

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        cancel = tool_input.tool_args.get("cancel")
        cancelled = self.brain.cancel_reminder(cancel) if cancel else None
        out: dict[str, Any] = {"pending": [{"id": r["id"], "message": r["message"], "at": r["at"]} for r in self.brain.reminders]}
        if cancel:
            out["cancelled"] = bool(cancelled)
        return _out(out)


class AutopilotStatusTool(_Tool):
    name = "autopilot_status"
    description = "Battery autopilot mode and its latest decisions with the reasons (top-up and evening export)."
    parameters = vol.Schema({vol.Optional("count", default=3): vol.All(int, vol.Range(min=1, max=10))})

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        ap, n = self.brain.autopilot, tool_input.tool_args.get("count", 3)
        keep = ("window", "do", "reason", "result", "source", "kw", "target_soc", "floor_soc", "outcome", "time")
        return _out({
            "mode": ap.mode,
            "active": ap.active,
            "decisions": [{k: d[k] for k in keep if k in d} for d in ap.decisions[-n:][::-1]],
        })


class HouseStatusTool(_Tool):
    name = "house_status"
    description = "Security sweep, house health issues, visitors today and parcels waiting."
    parameters = vol.Schema({})

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        b = self.brain
        return _out({
            "security": b.security.check(),
            "health_issues": list(b.health),
            "visitors_today": b.visitors.today_count(),
            "parcels_waiting": b.visitors.parcels_waiting,
            "recent_visitors": [f"{v['kind']}: {v['text']}" for v in b.visitors.log[-5:][::-1]],
        })


class TimelineTool(_Tool):
    name = "timeline"
    description = "What happened recently around the house, newest first, plus this week's totals."
    parameters = vol.Schema({vol.Optional("count", default=10): vol.All(int, vol.Range(min=1, max=30))})

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        n = tool_input.tool_args.get("count", 10)
        return _out({"events": list(self.brain.timeline.items)[:n], "week": self.brain.timeline.week()})


class EnergyStatusTool(_Tool):
    name = "energy_status"
    description = "Current tariff period, rates, solar forecast, battery and EV storage."
    parameters = vol.Schema({})

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        self.brain.refresh()
        s = dict(self.brain.snapshot)
        s["next_change"] = s["next_change"].isoformat()
        return _out(s)


class RunRoutineTool(_Tool):
    name = "run_routine"
    description = "Run a saved Cortex routine by name (for example goodnight or leaving)."
    parameters = vol.Schema({vol.Required("name"): str})

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        name = tool_input.tool_args["name"]
        if name not in self.brain.routines.items:
            return _out({"error": f"No routine called {name}", "known": sorted(self.brain.routines.items)})
        await self.brain.routines.run(name)
        return _out({"ran": name})


class SecurityCheckTool(_Tool):
    name = "security_check"
    description = "Read-only check for open doors and windows, unlocked locks and disarmed alarms."
    parameters = vol.Schema({})

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        return _out(self.brain.security.check())


class CortexAPI(llm.API):
    """The ``cortex`` LLM API."""

    def __init__(self, hass: HomeAssistant, brain: Cortex) -> None:
        super().__init__(hass=hass, id=DOMAIN, name="Cortex")
        self.brain = brain

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        tools: list[llm.Tool] = [
            RememberTool(self.brain),
            RecallTool(self.brain),
            ForgetTool(self.brain),
            RemindTool(self.brain),
            RemindersTool(self.brain),
            EnergyStatusTool(self.brain),
            AutopilotStatusTool(self.brain),
            HouseStatusTool(self.brain),
            TimelineTool(self.brain),
            RunRoutineTool(self.brain),
            SecurityCheckTool(self.brain),
        ]
        if self.brain.routines.items:
            prompt_routines = ", ".join(sorted(self.brain.routines.items))
        top = self.brain.book.recall("", 5)
        prompt = PROMPT + f" Now: {dt_util.now().strftime('%A %d %B %H:%M')}."
        if self.brain.routines.items:
            prompt += " Routines you can run: " + prompt_routines + "."
        if top:
            prompt += " Known so far: " + "; ".join(m.text for m in top) + "."
        return llm.APIInstance(api=self, api_prompt=prompt, llm_context=llm_context, tools=tools)
