import json

from homeassistant.core import HomeAssistant, SupportsResponse
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.cortex import autopilot_rules as r
from custom_components.cortex.const import DEFAULTS, DOMAIN

CTX = dict(
    soc=40, battery_kwh=50, pv_today=30, pv_tomorrow=30, avg_daily_load=25, night_share=0.35,
    ev_plugged=True, ev_need_kwh=8, shoulder=11.11, off_peak=32.12, peak=41.9, fit_evening=28,
    feed_in_now=28, topup_kw=5, export_kw=7, export_floor=30, business_day=True,
)


# ---- pure rules ------------------------------------------------------------
def test_baseline_topup_buys_what_solar_cannot_cover():
    d = r.baseline("topup", CTX)
    assert d["do"] and d["kw"] == 5 and 85 <= d["target_soc"] <= 95


def test_baseline_topup_skips_when_solar_fills_battery():
    d = r.baseline("topup", dict(CTX, soc=90, pv_today=60))
    assert not d["do"] and "solar" in d["reason"]


def test_baseline_topup_skips_when_margin_thin():
    assert not r.baseline("topup", dict(CTX, fit_evening=12))["do"]


def test_baseline_export_keeps_overnight_floor():
    d = r.baseline("export", dict(CTX, soc=95))
    assert d["do"] and d["floor_soc"] >= 30
    assert not r.baseline("export", dict(CTX, soc=31))["do"]
    assert not r.baseline("export", dict(CTX, soc=95, feed_in_now=3))["do"]


def test_baseline_unknown_soc():
    assert not r.baseline("topup", dict(CTX, soc=None))["do"]


def test_parse_handles_fences_prose_and_junk():
    assert r.parse('Sure!\n```json\n{"do": true, "kw": 4}\n```') == {"do": True, "kw": 4}
    assert r.parse("no json here") is None
    assert r.parse("") is None and r.parse(None) is None
    assert r.parse('{"a": {"b": 1}} trailing') == {"a": {"b": 1}}


def test_validate_clamps_model_overreach():
    base = r.baseline("topup", CTX)
    d = r.validate("topup", {"do": True, "kw": 50, "target_soc": 250}, CTX, base)
    assert d["kw"] == 5 and d["target_soc"] == 100 and d["source"] == "llm"
    e = r.validate("export", {"do": True, "kw": 99, "floor_soc": 2}, dict(CTX, soc=95), r.baseline("export", dict(CTX, soc=95)))
    assert e["kw"] == 7 and e["floor_soc"] == 30  # cannot go below the configured floor


def test_validate_refuses_unsafe_actions():
    base = r.baseline("topup", CTX)
    assert not r.validate("topup", {"do": True}, dict(CTX, soc=99), base)["do"]
    exp_base = r.baseline("export", dict(CTX, soc=95))
    assert not r.validate("export", {"do": True}, dict(CTX, soc=95, feed_in_now=5), exp_base)["do"]
    assert not r.validate("export", {"do": True, "floor_soc": 60}, dict(CTX, soc=61), exp_base)["do"]


def test_validate_falls_back_to_baseline_on_bad_reply():
    base = r.baseline("topup", CTX)
    d = r.validate("topup", None, CTX, base)
    assert d["source"] == "baseline" and d["do"] == base["do"]
    assert r.validate("topup", {"kw": 3}, CTX, base)["source"] == "baseline"


def test_model_may_decline():
    base = r.baseline("topup", CTX)
    d = r.validate("topup", {"do": False, "reason": "rain tomorrow, keep it"}, CTX, base)
    assert not d["do"] and "rain" in d["reason"]


# ---- integration -----------------------------------------------------------
async def _setup(hass: HomeAssistant, **opts):
    hass.states.async_set("sensor.neovolt_online_soc", "40")
    hass.states.async_set("sensor.pv_forecast_ingleburn", "30")
    hass.states.async_set("sensor.byd_sealion_7_battery_level", "50")
    entry = MockConfigEntry(domain=DOMAIN, title="Cortex", data={}, options={**DEFAULTS, **opts})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]


def _model(hass, reply):
    asked = []

    async def process(call):
        asked.append(call.data["text"])
        return {"response": {"speech": {"plain": {"speech": reply}}}}

    hass.services.async_register("conversation", "process", process, supports_response=SupportsResponse.ONLY)
    return asked


def _device(hass):
    return (
        async_mock_service(hass, "number", "set_value"),
        async_mock_service(hass, "select", "select_option"),
        async_mock_service(hass, "button", "press"),
        async_mock_service(hass, "notify", "send_message"),
    )


async def test_auto_mode_follows_model_within_limits(hass: HomeAssistant):
    numbers, selects, _, _ = _device(hass)
    asked = _model(hass, json.dumps({"do": True, "kw": 4, "target_soc": 85, "reason": "rain tomorrow"}))
    brain = await _setup(hass, autopilot_mode="auto")
    d = await brain.autopilot.decide("topup")
    assert d["result"] == "started" and d["source"] == "llm" and d["kw"] == 4
    assert {c.data["value"] for c in numbers} >= {4.0, 85.0}
    assert selects[-1].data["option"] == "Force Charge"
    assert "AGL" in asked[0] and brain.autopilot.active["window"] == "topup"
    assert hass.states.get("sensor.cortex_autopilot") is not None


async def test_shadow_mode_never_acts(hass: HomeAssistant):
    numbers, selects, _, pushes = _device(hass)
    _model(hass, '{"do": true, "kw": 5, "target_soc": 90}')
    hass.states.async_set("notify.iphone_2", "unknown")
    brain = await _setup(hass, autopilot_mode="shadow")
    d = await brain.autopilot.decide("topup")
    assert d["do"] and d["result"] == "advice"
    assert not numbers and not selects
    assert pushes and "advice" in pushes[0].data["message"].lower()


async def test_bad_model_reply_uses_rules(hass: HomeAssistant):
    _device(hass)
    _model(hass, "I think you should charge, probably!")
    brain = await _setup(hass, autopilot_mode="auto")
    d = await brain.autopilot.decide("topup")
    assert d["source"] == "baseline" and d["result"] == "started"


async def test_rules_only_when_ai_disabled_or_budget_spent(hass: HomeAssistant):
    _device(hass)
    asked = _model(hass, '{"do": false}')
    brain = await _setup(hass, autopilot_mode="shadow", autopilot_use_ai=False)
    assert (await brain.autopilot.decide("topup"))["source"] == "baseline" and not asked
    brain.opts["autopilot_use_ai"] = True
    brain.opts["ai_per_hour"] = 0
    assert (await brain.autopilot.decide("topup"))["source"] == "baseline" and not asked


async def test_manual_execute_override_and_service(hass: HomeAssistant):
    numbers, selects, _, _ = _device(hass)
    _model(hass, "no json")
    await _setup(hass, autopilot_mode="shadow")
    res = await hass.services.async_call(
        DOMAIN, "autopilot_decide", {"window": "topup", "execute": True}, blocking=True, return_response=True
    )
    assert res["decision"]["result"] == "started" and selects[-1].data["option"] == "Force Charge"


async def test_finish_books_outcome_and_only_stops_own_dispatch(hass: HomeAssistant):
    _, selects, presses, _ = _device(hass)
    _model(hass, "no json")
    brain = await _setup(hass, autopilot_mode="auto")
    await brain.autopilot.finish("Force Charge")  # nothing active: no-op
    assert not presses
    await brain.autopilot.decide("topup")
    hass.states.async_set("sensor.neovolt_online_soc", "90")
    hass.states.async_set("select.neovolt_neovoltlocal_dispatch_mode", "Force Charge")
    await brain.autopilot.finish("Force Discharge")  # wrong mode: ignored
    assert brain.autopilot.active
    await brain.autopilot.finish("Force Charge")
    assert brain.autopilot.active is None and presses
    assert "25.0 kWh" in brain.autopilot.decisions[-1]["outcome"]
    assert brain.timeline.today().get("autopilot_cents", 0) < 0  # buying costs money


async def test_autopilot_overrides_plain_timers(hass: HomeAssistant):
    brain = await _setup(hass, autopilot_mode="auto", auto_topup=True)
    assert brain.autopilot.controls
    brain2_mode = brain.opts["autopilot_mode"]
    assert brain2_mode == "auto"


async def test_off_mode_schedules_nothing(hass: HomeAssistant):
    brain = await _setup(hass, autopilot_mode="off")
    assert brain.autopilot.mode == "off" and not brain.autopilot._unsubs
