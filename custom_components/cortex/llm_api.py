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
    "Energy questions: use energy_status instead of guessing."
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
    description = "Speak a reminder aloud after a number of minutes."
    parameters = vol.Schema(
        {vol.Required("message"): str, vol.Required("in_minutes"): vol.All(int, vol.Range(min=1))}
    )

    async def async_call(self, hass, tool_input, llm_context) -> dict[str, Any]:
        args = tool_input.tool_args
        from datetime import timedelta

        item = self.brain.add_reminder(args["message"], dt_util.now() + timedelta(minutes=args["in_minutes"]))
        return _out({"reminder": item["id"], "at": item["at"]})


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
            EnergyStatusTool(self.brain),
            RunRoutineTool(self.brain),
            SecurityCheckTool(self.brain),
        ]
        if self.brain.routines.items:
            prompt_routines = ", ".join(sorted(self.brain.routines.items))
        top = self.brain.book.recall("", 5)
        prompt = PROMPT
        if self.brain.routines.items:
            prompt += " Routines you can run: " + prompt_routines + "."
        if top:
            prompt += " Known so far: " + "; ".join(m.text for m in top) + "."
        return llm.APIInstance(api=self, api_prompt=prompt, llm_context=llm_context, tools=tools)
