"""Autopilot decision rules. Pure Python, no Home Assistant imports.

The model proposes; these rules bound it. A reply that is missing, malformed or
outside the limits falls back to (or is clamped by) the baseline plan.
"""

from __future__ import annotations

import json
import re
from typing import Any

ROUND_TRIP = 0.9  # battery round-trip efficiency
SOLAR_TO_BATTERY = 0.9
MIN_MARGIN_C = 2.0  # cents per kWh the evening export must beat the cheap import by
TOPUP, EXPORT = "topup", "export"


def margin(ctx: dict[str, Any]) -> float:
    """Cents per kWh gained by buying in the shoulder window and exporting in the evening."""
    return ctx["fit_evening"] * ROUND_TRIP - ctx["shoulder"]


def night_kwh(ctx: dict[str, Any]) -> float:
    return ctx["avg_daily_load"] * ctx["night_share"]


def night_floor(ctx: dict[str, Any]) -> float:
    """Lowest battery level (%) that still covers the night load, whatever tomorrow's solar looks like."""
    cap = ctx["battery_kwh"] or 1.0
    return round(max(ctx["export_floor"], min(90.0, night_kwh(ctx) / cap * 100 + 10)), 1)


def baseline(window: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministic plan from the economics. Always valid."""
    soc, cap = ctx.get("soc"), ctx["battery_kwh"]
    if soc is None:
        return {"window": window, "do": False, "reason": "battery level unknown"}
    if window == TOPUP:
        room = cap * (100 - soc) / 100
        if margin(ctx) <= MIN_MARGIN_C:
            return {"window": window, "do": False, "reason": "evening export margin too thin to top up"}
        day_load = ctx["avg_daily_load"] * (1 - ctx["night_share"])
        ev = ctx["ev_need_kwh"] if ctx.get("ev_plugged") else 0.0
        pv = ctx.get("pv_today")
        spare = 0.0 if pv is None else max(pv - day_load - ev, 0.0) * SOLAR_TO_BATTERY
        need = room - spare
        if need < 1.5:
            return {"window": window, "do": False, "reason": f"solar should fill the battery ({spare:.0f} kWh spare)"}
        target = min(100.0, soc + need / cap * 100)
        return {
            "window": window, "do": True, "kw": ctx["topup_kw"], "target_soc": round(target),
            "reason": f"need {need:.1f} kWh from the grid at {ctx['shoulder']:g}c to export at {ctx['fit_evening']:g}c",
        }
    floor = night_floor(ctx)
    if ctx["feed_in_now"] < 20:
        return {"window": window, "do": False, "reason": "feed-in rate is low right now"}
    avail = cap * (soc - floor) / 100
    if avail < 2:
        return {"window": window, "do": False, "reason": f"only {max(avail, 0):.1f} kWh above the {floor:.0f}% floor"}
    return {
        "window": window, "do": True, "kw": ctx["export_kw"], "floor_soc": round(floor),
        "reason": f"{avail:.1f} kWh above the {floor:.0f}% floor at {ctx['feed_in_now']:g}c",
    }


def parse(text: str | None) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model reply."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(text)):
            depth += text[end] == "{"
            depth -= text[end] == "}"
            if depth == 0:
                try:
                    value = json.loads(text[start : end + 1])
                except ValueError:
                    break
                return value if isinstance(value, dict) else None
        start = text.find("{", start + 1)
    return None


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def validate(window: str, raw: dict[str, Any] | None, ctx: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Bound a model proposal. Returns the decision to act on."""
    if not raw or "do" not in raw:
        return {**base, "source": "baseline", "baseline": base}
    soc = ctx.get("soc")
    reason = str(raw.get("reason") or base.get("reason") or "")[:240]
    out: dict[str, Any] = {"window": window, "do": bool(raw.get("do")), "reason": reason, "source": "llm", "baseline": base}
    if soc is None:
        out.update(do=False, reason="battery level unknown")
        return out
    if window == TOPUP:
        if out["do"]:
            if soc >= 98 or margin(ctx) <= 0:
                out.update(do=False, reason="battery already full or no price margin")
            else:
                out["kw"] = round(clamp(_num(raw.get("kw"), ctx["topup_kw"]), 0.5, ctx["topup_kw"]), 1)
                out["target_soc"] = round(clamp(_num(raw.get("target_soc"), base.get("target_soc", 100)), soc + 1, 100))
    else:
        if out["do"]:
            # Solar tomorrow cannot power tonight: the model may raise the floor but never go below the night need.
            low = night_floor(ctx)
            floor = round(clamp(_num(raw.get("floor_soc"), base.get("floor_soc", low)), low, 90))
            if raw.get("floor_soc") is not None and _num(raw.get("floor_soc"), floor) < low - 0.5:
                out["reason"] = (out["reason"] + f" (floor raised to {floor}% to cover the night)")[:260]
            if ctx["feed_in_now"] < 15 or soc <= floor + 2:
                out.update(do=False, reason="feed-in too low or battery near the floor")
            else:
                out["kw"] = round(clamp(_num(raw.get("kw"), ctx["export_kw"]), 0.5, ctx["export_kw"]), 1)
                out["floor_soc"] = floor
    return out


def prompt(window: str, ctx: dict[str, Any], base: dict[str, Any]) -> str:
    keys = (
        "now", "soc", "battery_kwh", "battery_usable_kwh", "pv_today", "pv_tomorrow", "solar_day", "avg_daily_load",
        "night_share", "ev_plugged", "ev_need_kwh", "shoulder", "off_peak", "peak", "fit_evening", "feed_in_now",
        "business_day", "topup_kw", "export_kw", "export_floor", "recent",
    )
    facts = {k: ctx.get(k) for k in keys}
    facts["margin_c_per_kwh"] = round(margin(ctx), 1)
    facts["night_floor_soc"] = night_floor(ctx)
    data = json.dumps(facts, default=str)
    if window == TOPUP:
        ask = (
            'Decide whether to charge the battery from the grid now (cheap shoulder window). '
            'Reply with ONLY this JSON: {"do": true|false, "kw": number, "target_soc": number, "reason": "short"}.'
        )
    else:
        ask = (
            'Decide whether to export battery energy to the grid now (evening feed-in window). '
            'Reply with ONLY this JSON: {"do": true|false, "kw": number, "floor_soc": number, "reason": "short"}.'
        )
    return (
        "You are the energy planner for an Australian home on an AGL time-of-use plan. Rates are cents per kWh. "
        "Buying in the shoulder window is cheap; exporting in the evening pays the feed-in rate; "
        "never let the battery run flat before morning (night_floor_soc is the lowest safe level; exports below it are overridden). "
        "A top-up only pays when margin_c_per_kwh is clearly positive and solar will not fill the battery anyway. "
        "Learn from recent decisions: each shows its result and, when finished, the dollars it earned or cost. "
        "Do not call tools. Do not think at length: answer immediately with the JSON. "
        f"{ask} Data: {data} Rule-based suggestion: {json.dumps(base)}"
    )


def describe(d: dict[str, Any]) -> str:
    label = "grid top-up" if d["window"] == TOPUP else "evening export"
    if not d.get("do"):
        return f"No {label}: {d.get('reason', '')}".strip()
    tail = f"to {d['target_soc']}%" if d["window"] == TOPUP else f"down to {d['floor_soc']}%"
    return f"{label.capitalize()} {d['kw']:g} kW {tail}: {d.get('reason', '')}".strip()
