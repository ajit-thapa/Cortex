"""Routine and chain detection from plain statistics, plus the suggestion queue.

The detection functions are pure Python. ``Learning`` wires them to Home Assistant.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import Event, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.util import dt as dt_util

from .feature import Feature

Observation = tuple[str, str, datetime]  # (entity_id, state, when)

# state -> service, for the domains we know how to act on
ACTIONS: dict[str, dict[str, str]] = {
    "light": {"on": "turn_on", "off": "turn_off"},
    "switch": {"on": "turn_on", "off": "turn_off"},
    "fan": {"on": "turn_on", "off": "turn_off"},
    "input_boolean": {"on": "turn_on", "off": "turn_off"},
    "lock": {"locked": "lock", "unlocked": "unlock"},
    "cover": {"open": "open_cover", "closed": "close_cover"},
}
MAX_OBS = 4000
KEEP_DAYS = 30


def service_for(entity_id: str, state: str) -> str | None:
    domain = entity_id.split(".", 1)[0]
    action = ACTIONS.get(domain, {}).get(state)
    return f"{domain}.{action}" if action else None


def daytype(day: date) -> str:
    return "weekend" if day.weekday() >= 5 else "weekday"


def _digest(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:8]  # noqa: S324 - id only


def detect_routines(
    obs: list[Observation],
    today: date,
    window_days: int = 21,
    min_days: int = 4,
    tolerance: int = 25,
    ratio: float = 0.6,
) -> list[dict[str, Any]]:
    """Find things that happen at about the same time on the same kind of day."""
    recent = [o for o in obs if 0 <= (today - o[2].date()).days <= window_days]
    if not recent:
        return []
    earliest = min(o[2].date() for o in recent)
    groups: dict[tuple[str, str, str], dict[date, int]] = {}
    for entity, state, when in recent:
        minute = when.hour * 60 + when.minute
        days = groups.setdefault((entity, state, daytype(when.date())), {})
        days[when.date()] = min(minute, days.get(when.date(), minute))
    span = (today - earliest).days + 1
    results = []
    for (entity, state, kind), days in groups.items():
        if len(days) < min_days:
            continue
        minutes = sorted(days.values())
        best = max(minutes, key=lambda c: sum(1 for m in minutes if abs(m - c) <= tolerance))
        members = sorted(m for m in minutes if abs(m - best) <= tolerance)
        if len(members) < min_days:
            continue
        available = sum(1 for i in range(span) if daytype(today - timedelta(days=i)) == kind)
        if available and len(members) / available < ratio:
            continue
        results.append(
            {
                "type": "routine",
                "id": _digest("routine", entity, state, kind),
                "entity_id": entity,
                "state": state,
                "daytype": kind,
                "at": members[len(members) // 2],
                "days": len(members),
            }
        )
    return results


def detect_chains(
    obs: list[Observation],
    today: date,
    window_days: int = 21,
    follow_seconds: int = 300,
    min_days: int = 4,
    ratio: float = 0.7,
) -> list[dict[str, Any]]:
    """Find "after A, B follows within a few minutes" patterns."""
    events = sorted(
        (o for o in obs if 0 <= (today - o[2].date()).days <= window_days), key=lambda o: o[2]
    )
    occurrences: dict[tuple[str, str], int] = {}
    pairs: dict[tuple[tuple[str, str], tuple[str, str]], list[date]] = {}
    for i, (ea, sa, ta) in enumerate(events):
        occurrences[(ea, sa)] = occurrences.get((ea, sa), 0) + 1
        seen: set[tuple[str, str]] = set()
        for eb, sb, tb in events[i + 1 :]:
            if (tb - ta).total_seconds() > follow_seconds:
                break
            if eb == ea or (eb, sb) in seen:
                continue
            seen.add((eb, sb))
            pairs.setdefault(((ea, sa), (eb, sb)), []).append(ta.date())
    results = []
    for (a, b), when in pairs.items():
        days = set(when)
        if len(days) < min_days or len(when) / occurrences[a] < ratio:
            continue
        results.append(
            {
                "type": "chain",
                "id": _digest("chain", *a, *b),
                "if_entity": a[0],
                "if_state": a[1],
                "entity_id": b[0],
                "state": b[1],
                "days": len(days),
            }
        )
    return results


def describe(item: dict[str, Any], names: dict[str, str]) -> str:
    def name(entity: str) -> str:
        return names.get(entity, entity)

    verb = (service_for(item["entity_id"], item["state"]) or "").split(".")[-1].replace("_", " ")
    if item["type"] == "routine":
        hh, mm = divmod(int(item["at"]), 60)
        when = "on weekends" if item["daytype"] == "weekend" else "on weekdays"
        return f"You usually {verb} {name(item['entity_id'])} around {hh:02d}:{mm:02d} {when}."
    return (
        f"After {name(item['if_entity'])} goes {item['if_state']}, "
        f"you usually {verb} {name(item['entity_id'])}."
    )


class Learning(Feature):
    name = "learning"

    def __init__(self, brain) -> None:
        super().__init__(brain)
        self.obs: list[list[str]] = []
        self.suggestions: list[dict[str, Any]] = []

    def load(self, data) -> None:
        data = data or {}
        self.obs = data.get("obs", [])
        self.suggestions = data.get("suggestions", [])

    def dump(self) -> dict[str, Any]:
        return {"obs": self.obs[-MAX_OBS:], "suggestions": self.suggestions[-60:]}

    @property
    def pending(self) -> list[dict[str, Any]]:
        return [s for s in self.suggestions if s["status"] == "new"]

    async def start(self) -> None:
        from .const import CONF_LEARN

        ids = [e for e in (self.brain.opts.get(CONF_LEARN) or []) if service_for(e, "on") or service_for(e, "locked") or service_for(e, "open")]
        if ids:
            self._unsubs.append(async_track_state_change_event(self.hass, ids, self._on_change))
            self._unsubs.append(
                async_track_time_change(self.hass, self._nightly, hour=3, minute=30, second=0)
            )

    @callback
    def _on_change(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None or old is None or new.state == old.state:
            return
        if new.state in ("unknown", "unavailable") or old.state in ("unknown", "unavailable"):
            return
        if not service_for(new.entity_id, new.state):
            return
        self.obs.append([new.entity_id, new.state, dt_util.now().isoformat()])
        if len(self.obs) > MAX_OBS:
            self.obs = self.obs[-MAX_OBS:]

    def observations(self) -> list[Observation]:
        cutoff = dt_util.now() - timedelta(days=KEEP_DAYS)
        out = []
        for entity, state, stamp in self.obs:
            when = dt_util.parse_datetime(stamp)
            if when and when >= cutoff:
                out.append((entity, state, dt_util.as_local(when)))
        return out

    async def _nightly(self, _now: datetime) -> None:
        await self.analyse()

    async def analyse(self) -> list[dict[str, Any]]:
        """Look for new patterns. Returns the suggestions added this run."""
        obs = self.observations()
        today = dt_util.now().date()
        known = {s["id"] for s in self.suggestions}
        names = {
            e: (self.hass.states.get(e).attributes.get("friendly_name", e) if self.hass.states.get(e) else e)
            for e in {o[0] for o in obs}
        }
        added = []
        for item in detect_routines(obs, today) + detect_chains(obs, today):
            if item["id"] in known or len(self.pending) + len(added) >= 20:
                continue
            record = {
                "id": item["id"],
                "type": item["type"],
                "text": describe(item, names),
                "data": item,
                "status": "new",
                "created": dt_util.now().isoformat(timespec="seconds"),
            }
            self.suggestions.append(record)
            added.append(record)
        if added:
            self.brain.save()
            for record in added[:2]:
                await self.brain.speaker.push(
                    f"{record['text']} Automate it? Open Cortex or call cortex.accept_suggestion with id {record['id']}.",
                    title="Cortex noticed a pattern",
                )
            self.brain.record("suggestions", len(added))
            self.brain.log("learning", f"{len(added)} new suggestion(s)")
        return added

    def get(self, ident: str) -> dict[str, Any] | None:
        return next((s for s in self.suggestions if s["id"] == ident), None)

    def dismiss(self, ident: str) -> bool:
        item = self.get(ident)
        if item is None:
            return False
        item["status"] = "dismissed"
        self.brain.save()
        return True

    def accept(self, ident: str) -> dict[str, Any]:
        """Turn a suggestion into a routine."""
        item = self.get(ident)
        if item is None:
            raise ValueError("no such suggestion")
        data = item["data"]
        service = service_for(data["entity_id"], data["state"])
        step = {"service": service, "target": {"entity_id": data["entity_id"]}}
        name = f"auto-{item['id']}"
        if item["type"] == "routine":
            hh, mm = divmod(int(data["at"]), 60)
            routine = {
                "name": name,
                "steps": [step],
                "schedule": {
                    "at": f"{hh:02d}:{mm:02d}",
                    "days": "weekends" if data["daytype"] == "weekend" else "weekdays",
                },
            }
        else:
            routine = {
                "name": name,
                "steps": [step],
                "on_state": {"entity_id": data["if_entity"], "to": data["if_state"], "cooldown": 300},
            }
        saved = self.brain.routines.save(routine)
        item["status"] = "accepted"
        self.brain.save()
        self.brain.log("learning", f"Automated: {item['text']}")
        return saved
