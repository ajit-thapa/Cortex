"""Event timeline and daily statistics."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .feature import Feature

# How a statistic combines within a day, and across days for a report.
DAY_MODE = {"soc_min": "min", "soc_max": "max", "pv_forecast": "set"}
KEEP_DAYS = 35


class Timeline(Feature):
    name = "timeline"

    def __init__(self, brain) -> None:
        super().__init__(brain)
        self.items: deque[dict[str, Any]] = deque(maxlen=200)
        self.daily: dict[str, dict[str, float]] = {}

    def load(self, data) -> None:
        data = data or {}
        self.items = deque(data.get("items", []), maxlen=200)
        self.daily = data.get("daily", {})

    def dump(self) -> dict[str, Any]:
        keep = sorted(self.daily)[-KEEP_DAYS:]
        return {"items": list(self.items), "daily": {d: self.daily[d] for d in keep}}

    def add(self, kind: str, text: str) -> None:
        self.items.appendleft(
            {"time": dt_util.now().isoformat(timespec="seconds"), "kind": kind, "text": text[:240]}
        )

    def record(self, key: str, value: float = 1) -> None:
        day = self.daily.setdefault(dt_util.now().date().isoformat(), {})
        mode = DAY_MODE.get(key, "add")
        if key not in day:
            day[key] = value
        elif mode == "add":
            day[key] += value
        elif mode == "min":
            day[key] = min(day[key], value)
        elif mode == "max":
            day[key] = max(day[key], value)
        else:
            day[key] = value

    def week(self) -> dict[str, float]:
        """Totals (or min/max/mean) over the last seven days."""
        today = dt_util.now().date()
        days = [(today - timedelta(days=i)).isoformat() for i in range(7)]
        values: dict[str, list[float]] = {}
        for day in days:
            for key, value in self.daily.get(day, {}).items():
                values.setdefault(key, []).append(value)
        out: dict[str, float] = {}
        for key, vals in values.items():
            mode = DAY_MODE.get(key, "add")
            if mode == "min":
                out[key] = min(vals)
            elif mode == "max":
                out[key] = max(vals)
            elif mode == "set":
                out[key] = round(sum(vals) / len(vals), 1)
            else:
                out[key] = sum(vals)
        return out

    def today(self) -> dict[str, float]:
        return self.daily.get(dt_util.now().date().isoformat(), {})
