from datetime import date, datetime, timedelta, timezone

from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.cortex.const import DEFAULTS, DOMAIN
from custom_components.cortex.migrate import LEGACY
from custom_components.cortex.learning import detect_chains, detect_routines, service_for
from custom_components.cortex.heating import lead_minutes
from custom_components.cortex.visitors import parse_look

UTC = timezone.utc


async def _setup(hass: HomeAssistant, **opts):
    entry = MockConfigEntry(domain=DOMAIN, title="Cortex", data={}, options={**DEFAULTS, **LEGACY, **opts})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]


# ---- pure ------------------------------------------------------------------
def test_service_for():
    assert service_for("light.x", "on") == "light.turn_on"
    assert service_for("sensor.x", "on") is None


def test_detect_routines_finds_regular_evening_light():
    today = date(2026, 10, 30)
    obs = []
    for i in range(10):
        day = today - timedelta(days=i)
        when = datetime(day.year, day.month, day.day, 18, 30 + (i % 3), tzinfo=UTC)
        obs.append(("light.lounge", "on", when))
    found = detect_routines(obs, today)
    assert found and found[0]["entity_id"] == "light.lounge"
    assert 18 * 60 + 25 <= found[0]["at"] <= 18 * 60 + 35


def test_detect_routines_ignores_irregular():
    today = date(2026, 10, 30)
    obs = [
        ("light.x", "on", datetime(2026, 10, 30 - i, h, 0, tzinfo=UTC))
        for i, h in enumerate((6, 12, 19, 3, 22))
    ]
    assert detect_routines(obs, today) == []


def test_detect_chains():
    today = date(2026, 10, 30)
    obs = []
    for i in range(6):
        d = today - timedelta(days=i)
        t = datetime(d.year, d.month, d.day, 22, 0, tzinfo=UTC)
        obs += [("light.hall", "off", t), ("lock.front", "locked", t + timedelta(minutes=2))]
    chains = detect_chains(obs, today)
    assert any(c["if_entity"] == "light.hall" and c["entity_id"] == "lock.front" for c in chains)


def test_lead_minutes_and_parse_look():
    assert lead_minutes(16, 20, 0.1) == pytest.approx(40)
    assert lead_minutes(21, 20, 0.1) == 0
    assert parse_look("delivery: courier with a box") == ("delivery", "courier with a box")
    assert parse_look("a cat")[0] == "person"


# ---- routines ----------------------------------------------------------------
async def test_routine_save_and_run(hass: HomeAssistant):
    calls = async_mock_service(hass, "light", "turn_off")
    await _setup(hass, speakers=[], quiet_start="00:00:00", quiet_end="00:00:00")
    await hass.services.async_call(
        DOMAIN, "save_routine",
        {"name": "goodnight", "steps": [
            {"service": "light.turn_off", "target": {"entity_id": "light.lounge"}},
            {"delay": 0},
            {"say": "Goodnight"},
        ]},
        blocking=True, return_response=True,
    )
    res = await hass.services.async_call(
        DOMAIN, "run_routine", {"name": "goodnight"}, blocking=True, return_response=True
    )
    assert len(calls) == 1 and len(res["results"]) == 3


async def test_routine_rejects_bad_step(hass: HomeAssistant):
    await _setup(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "save_routine",
            {"name": "bad", "steps": [{"service": "not a service"}]},
            blocking=True, return_response=True,
        )


async def test_routine_on_state_trigger(hass: HomeAssistant):
    calls = async_mock_service(hass, "light", "turn_on")
    brain = await _setup(hass)
    brain.routines.save({
        "name": "porch", "steps": [{"service": "light.turn_on", "target": {"entity_id": "light.porch"}}],
        "on_state": {"entity_id": "binary_sensor.door", "to": "on", "cooldown": 0},
    })
    hass.states.async_set("binary_sensor.door", "off")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.door", "on")
    await hass.async_block_till_done()
    assert len(calls) == 1


# ---- security ----------------------------------------------------------------
async def test_security_check(hass: HomeAssistant):
    brain = await _setup(hass)
    assert brain.security.check()["ok"]
    hass.states.async_set("binary_sensor.back_door", "on", {"device_class": "door", "friendly_name": "Back door"})
    hass.states.async_set("lock.front", "unlocked", {"friendly_name": "Front lock"})
    result = brain.security.check()
    assert not result["ok"] and "Back door is open" in result["issues"] and "Front lock is unlocked" in result["issues"]
    out = await hass.services.async_call(DOMAIN, "security_check", {}, blocking=True, return_response=True)
    assert len(out["issues"]) == 2


async def test_night_watch_alerts_at_night_only(hass: HomeAssistant):
    pushes = async_mock_service(hass, "notify", "send_message")
    hass.states.async_set("notify.iphone_2", "unknown")
    hass.states.async_set("binary_sensor.window", "off", {"device_class": "window", "friendly_name": "Bedroom window"})
    await _setup(hass, night_start="00:00:00", night_end="23:59:59", quiet_start="00:00:00", quiet_end="00:00:00")
    hass.states.async_set("binary_sensor.window", "on", {"device_class": "window", "friendly_name": "Bedroom window"})
    await hass.async_block_till_done()
    assert len(pushes) == 1 and "Bedroom window" in pushes[0].data["message"]


async def test_night_watch_quiet_in_daytime(hass: HomeAssistant):
    pushes = async_mock_service(hass, "notify", "send_message")
    hass.states.async_set("notify.iphone_2", "unknown")
    hass.states.async_set("binary_sensor.window", "off", {"device_class": "window"})
    await _setup(hass, night_start="03:00:00", night_end="03:00:01", quiet_start="00:00:00", quiet_end="00:00:00")
    hass.states.async_set("binary_sensor.window", "on", {"device_class": "window"})
    await hass.async_block_till_done()
    assert not pushes


# ---- visitors / camera -------------------------------------------------------
async def test_visitor_parcel_flow(hass: HomeAssistant):
    async_mock_service(hass, "notify", "send_message")
    hass.states.async_set("notify.iphone_2", "unknown")
    seen = []

    async def generate(call):
        seen.append(call.data)
        return {"data": "parcel: box left on the mat"}

    hass.services.async_register(
        "ai_task", "generate_data", generate, supports_response=SupportsResponse.ONLY
    )
    brain = await _setup(hass, ai_task="ai_task.test", quiet_start="00:00:00", quiet_end="00:00:00")
    await hass.services.async_call(DOMAIN, "set_spot", {"camera": "camera.porch", "spot": "front porch"}, blocking=True)
    entry = await brain.visitors.handle_visitor("camera.porch")
    assert entry["kind"] == "parcel"
    assert "front porch" in seen[0]["instructions"]
    assert seen[0]["attachments"][0]["media_content_id"] == "media-source://camera/camera.porch"
    assert hass.states.get("sensor.cortex_parcels_waiting").state == "1"
    await hass.services.async_call(DOMAIN, "parcels_collected", {}, blocking=True)
    assert brain.visitors.parcels_waiting == 0


async def test_look_needs_ai_task_and_budget(hass: HomeAssistant):
    brain = await _setup(hass)
    with pytest.raises(HomeAssistantError):
        await brain.look("camera.x", "what?")
    hass.services.async_register(
        "ai_task", "generate_data", lambda call: {"data": "ok"}, supports_response=SupportsResponse.ONLY
    )
    brain.opts["ai_task"] = "ai_task.t"
    brain.opts["ai_per_hour"] = 1
    assert await brain.look("camera.x", "what?") == "ok"
    with pytest.raises(HomeAssistantError):
        await brain.look("camera.x", "what?")


# ---- motion lights -----------------------------------------------------------
async def test_motion_light_on_and_off(hass: HomeAssistant):
    ons = async_mock_service(hass, "light", "turn_on")
    offs = async_mock_service(hass, "light", "turn_off")
    brain = await _setup(hass)
    brain.motion_lights.save({
        "name": "hall", "motion": ["binary_sensor.hall"], "lights": ["light.hall"],
        "delay": 10, "only_dark": False,
    })
    hass.states.async_set("light.hall", "off")
    hass.states.async_set("binary_sensor.hall", "off")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.hall", "on")
    await hass.async_block_till_done()
    assert len(ons) == 1
    hass.states.async_set("binary_sensor.hall", "off")
    await hass.async_block_till_done()
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
    await hass.async_block_till_done()
    assert len(offs) == 1


# ---- heating -----------------------------------------------------------------
async def test_heating_prewarm(hass: HomeAssistant):
    modes = async_mock_service(hass, "climate", "set_hvac_mode")
    temps = async_mock_service(hass, "climate", "set_temperature")
    brain = await _setup(hass)
    now = dt_util.now()
    ready = (now + timedelta(minutes=30)).strftime("%H:%M")
    hass.states.async_set("climate.lounge", "off", {"current_temperature": 18})
    brain.heating.save({"name": "lounge", "climate": "climate.lounge", "target": 21, "ready_by": ready, "rate": 0.05})
    await brain.heating._tick(now)
    assert len(modes) == 1 and len(temps) == 1
    await brain.heating._tick(now)  # only once per day
    assert len(temps) == 1


# ---- briefing / weekly / backup ---------------------------------------------
async def test_briefing_sections_and_weekly(hass: HomeAssistant):
    hass.states.async_set("sensor.neovolt_online_soc", "50")
    hass.states.async_set("weather.home", "sunny", {"temperature": 24, "temperature_unit": "°C"})
    brain = await _setup(hass, weather_entity="weather.home")
    brain.refresh()
    text = brain.briefing.build(sections=["weather", "energy"], kind="morning")
    assert text.startswith("Good morning.") and "sunny" in text and "battery is at 50" in text
    brain.record("spoken", 3)
    brain.record("alerts", 1)
    week = brain.briefing.weekly_text()
    assert "spoke 3 times" in week and "1 safety alert" in week
    res = await hass.services.async_call(DOMAIN, "weekly_report", {}, blocking=True, return_response=True)
    assert "Week in review" in res["text"]


async def test_backup_and_restore(hass: HomeAssistant, tmp_path):
    hass.config.config_dir = str(tmp_path)
    brain = await _setup(hass)
    brain.remember("Wi-Fi is on the fridge", "fact")
    brain.routines.save({"name": "r1", "steps": [{"say": "hi"}]})
    out = await hass.services.async_call(DOMAIN, "backup", {}, blocking=True, return_response=True)
    assert out["path"].endswith(".json")
    brain.forget(brain.book.items[0].id)
    brain.routines.delete("r1")
    assert not brain.book.items and not brain.routines.items
    res = await hass.services.async_call(DOMAIN, "restore", {}, blocking=True, return_response=True)
    assert res["restored"].startswith("cortex-")
    assert [m.text for m in brain.book.items] == ["Wi-Fi is on the fridge"]
    assert "r1" in brain.routines.items
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "restore", {"file": "../../etc/passwd"}, blocking=True, return_response=True)


# ---- learning -----------------------------------------------------------------
async def test_learning_accept_creates_routine(hass: HomeAssistant):
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass, learn_entities=["light.lounge"])
    today = dt_util.now().date()
    for i in range(10):
        d = today - timedelta(days=i)
        when = dt_util.as_local(datetime(d.year, d.month, d.day, 18, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE))
        brain.learning.obs.append(["light.lounge", "on", when.isoformat()])
    added = await brain.learning.analyse()
    assert added
    waiting = len(brain.learning.pending)  # weekday and, depending on today's date, weekend patterns
    sid = brain.learning.pending[0]["id"]
    routine = await hass.services.async_call(
        DOMAIN, "accept_suggestion", {"id": sid}, blocking=True, return_response=True
    )
    assert routine["routine"]["name"] in brain.routines.items
    assert hass.states.get("sensor.cortex_routine_suggestions").state == str(waiting - 1)


# ---- watches with AI / voice room ---------------------------------------------
async def test_watch_ai_remark_is_rate_limited(hass: HomeAssistant):
    async_mock_service(hass, "notify", "send_message")
    asked = []

    async def process(call):
        asked.append(call.data["text"])
        return {"response": {"speech": {"plain": {"speech": "Probably just wind."}}}}

    hass.services.async_register("conversation", "process", process, supports_response=SupportsResponse.ONLY)
    spoken = async_mock_service(hass, "assist_satellite", "announce")
    brain = await _setup(hass, speakers=["assist_satellite.k"], quiet_start="00:00:00", quiet_end="00:00:00", ai_per_hour=1)
    hass.states.async_set("binary_sensor.gate", "off")
    brain.add_watch("binary_sensor.gate", "{name} is {state}", "on", cooldown=0, ai=True)
    hass.states.async_set("binary_sensor.gate", "on")
    await hass.async_block_till_done()
    assert spoken and "Probably just wind." in spoken[0].data["message"]
    hass.states.async_set("binary_sensor.gate", "off")
    hass.states.async_set("binary_sensor.gate", "on")
    await hass.async_block_till_done()
    assert len(asked) == 1  # budget of one per hour


async def test_voice_area_beats_motion(hass: HomeAssistant):
    brain = await _setup(hass)
    sp = brain.speaker
    sp._area_of = lambda e: {"assist_satellite.office": "office"}.get(e)
    sp.note_voice("assist_satellite.office")
    assert sp.likely_area() == "office"


# ---- Energy Studio -------------------------------------------------------------
async def test_overview_carries_studio_sources(hass: HomeAssistant, hass_ws_client):
    brain = await _setup(hass)
    assert brain.snapshot["low_solar"] == 30.0
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "cortex/overview"})
    msg = await client.receive_json()
    assert msg["success"]
    studio = msg["result"]["studio"]
    assert studio["pv"] == "sensor.sungrow_pv" and studio["grid"] == "sensor.neovolt_online_grid"
    assert studio["grid_invert"] is False and studio["day_pv"].endswith("pv_generated_today")
    assert msg["result"]["energy"]["low_solar"] == 30.0


# ---- house health --------------------------------------------------------------
async def test_health_names_offline_devices_after_a_grace_period(hass: HomeAssistant):
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass)
    hass.states.async_set("switch.pv_export", "unavailable", {"friendly_name": "Neovolt Online PV Export"})
    assert await brain.run_health() == []  # just went offline: not a fault yet
    brain._offline_since["switch.pv_export"] -= timedelta(minutes=31)
    assert await brain.run_health() == ["Neovolt Online PV Export is offline"]
    hass.states.async_set("switch.pv_export", "on", {"friendly_name": "Neovolt Online PV Export"})
    assert await brain.run_health() == [] and not brain._offline_since


async def test_health_ignore_list_and_battery_unit(hass: HomeAssistant):
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass, health_ignore=["switch.pv_export"])
    hass.states.async_set("switch.pv_export", "unavailable", {"friendly_name": "Neovolt Online PV Export"})
    brain._offline_since["switch.pv_export"] = dt_util.utcnow() - timedelta(hours=2)
    # a battery-class sensor that is not a percentage (a storage system's kWh) must not count as a dying battery
    hass.states.async_set("sensor.house_battery_energy", "3", {"device_class": "battery", "unit_of_measurement": "kWh", "friendly_name": "House battery"})
    hass.states.async_set("sensor.door_battery", "9", {"device_class": "battery", "unit_of_measurement": "%", "friendly_name": "Door"})
    assert await brain.run_health() == ["Door battery at 9%"]


# ---- battery control from the panel ---------------------------------------------
async def test_panel_set_options_and_manual_dispatch(hass: HomeAssistant, hass_ws_client):
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass, autopilot_mode="shadow", house_off_grid=False)
    hass.states.async_set("sensor.neovolt_online_soc", "80")
    sent = []
    for domain, svc in (("number", "set_value"), ("select", "select_option"), ("button", "press")):
        async def rec(call, d=domain, s=svc):
            sent.append((d, s, dict(call.data)))
        hass.services.async_register(domain, svc, rec)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "cortex/overview"})
    ctl = (await ws.receive_json())["result"]["control"]
    assert ctl["autopilot_mode"] == "shadow" and "export_kw" in ctl
    # change mode (rejects unknown keys and out of range values)
    await ws.send_json({"id": 2, "type": "cortex/set_options", "options": {"secret_key": 1}})
    assert not (await ws.receive_json())["success"]
    await ws.send_json({"id": 3, "type": "cortex/set_options", "options": {"export_kw": 99}})
    assert not (await ws.receive_json())["success"]
    await ws.send_json({"id": 4, "type": "cortex/set_options", "options": {"autopilot_mode": "off", "auto_topup": False, "export_kw": 6.5}})
    assert (await ws.receive_json())["success"]
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.options["autopilot_mode"] == "off" and entry.options["export_kw"] == 6.5
    # manual discharge uses the numbers from the panel
    await ws.send_json({"id": 5, "type": "cortex/action", "action": "manual_export", "kw": 4.0, "soc": 35})
    assert (await ws.receive_json())["result"]["result"] == "started"
    assert ("number", "set_value", {"entity_id": LEGACY["dispatch_power"], "value": 4.0}) in sent
    assert ("number", "set_value", {"entity_id": LEGACY["discharge_target"], "value": 35.0}) in sent
    assert any(d == "select" and x.get("option") == "Force Discharge" for d, _, x in sent)
    await ws.send_json({"id": 6, "type": "cortex/action", "action": "manual_stop"})
    assert (await ws.receive_json())["result"]["result"] == "stopped"


async def test_panel_object_actions_use_target_not_id(hass: HomeAssistant, hass_ws_client):
    """The websocket protocol owns "id"; object ids travel in "target" or HA rejects the message."""
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass)
    mem = brain.remember("Bins on Tuesday", "fact", "test")
    item = brain.add_reminder("Call plumber", dt_util.now() + timedelta(hours=1))
    brain.routines.save({"name": "tidy", "steps": [{"service": "light.turn_off", "target": {"entity_id": "light.x"}}]})
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "cortex/memory_delete", "target": mem.id})
    assert (await ws.receive_json())["result"]["deleted"]
    await ws.send_json({"id": 2, "type": "cortex/cancel", "kind": "reminder", "target": item["id"]})
    assert (await ws.receive_json())["result"]["ok"]
    await ws.send_json({"id": 3, "type": "cortex/action", "action": "delete_routine", "target": "tidy"})
    assert (await ws.receive_json())["success"] and "tidy" not in brain.routines.items


async def test_overview_advice_plans_and_settings(hass: HomeAssistant, hass_ws_client):
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "cortex/overview"})
    res = (await ws.receive_json())["result"]
    assert res["advice"] and res["plans"] == [] and "health_ignore" in res["settings"]
    plan = {"id": "p1", "name": "Flat", "supply": 100, "import_default": 30, "fit_default": 5,
            "import": [{"from": 10, "to": 14, "rate": 10, "days": "all"}], "junk": 1}
    await ws.send_json({"id": 2, "type": "cortex/plans_save", "plans": [plan]})
    out = await ws.receive_json()
    assert out["success"] and "junk" not in out["result"]["plans"][0] and brain.plans[0]["name"] == "Flat"
    await ws.send_json({"id": 3, "type": "cortex/plans_save", "plans": [{**plan, "supply": -5}]})
    assert not (await ws.receive_json())["success"]
    await ws.send_json({"id": 4, "type": "cortex/set_options", "options": {"health_ignore": ["switch.x"], "ai_per_hour": 20}})
    assert (await ws.receive_json())["success"]
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(DOMAIN)[0].options["health_ignore"] == ["switch.x"]


async def test_ev_first_export_guard(hass: HomeAssistant):
    """EV charging during a forced export: battery feeds the car first, export stops once supply is covered."""
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass)
    sent = []
    for domain, svc in (("number", "set_value"), ("select", "select_option"), ("button", "press")):
        async def rec(call, d=domain, s=svc):
            sent.append((d, s, dict(call.data)))
        hass.services.async_register(domain, svc, rec)
    o, en = brain.opts, brain.energy
    evening = dt_util.now().replace(hour=18, minute=0)
    hass.states.async_set(o["dispatch_mode"], "Force Discharge")
    hass.states.async_set(o["dispatch_power"], "7")
    hass.states.async_set(o["studio_ev"], "7.2", {"unit_of_measurement": "kW"})
    hass.states.async_set(o["studio_pv"], "0", {"unit_of_measurement": "kW"})
    hass.states.async_set(o["studio_grid"], "-1", {"unit_of_measurement": "kW"})
    hass.states.async_set(o["studio_battery"], "9.0", {"unit_of_measurement": "kW"})  # inverted: discharging 9 kW
    hass.states.async_set(o["studio_day_export"], "2.0")
    en.track_export(evening)
    hass.states.async_set(o["studio_day_export"], "4.0")  # 2 kWh at 28c = 56c
    assert round(en.track_export(evening)) == 56 and en.supply_left() > 1
    # not covered yet: raise battery output so it covers EV + house + export, capped at the battery maximum
    assert await en.ev_guard(evening) == "adjusted"
    assert ("number", "set_value", {"entity_id": o["dispatch_power"], "value": 10.0}) in sent
    # covered: keep the battery on the EV and house, exporting only the 200 W trickle
    hass.states.async_set(o["studio_day_export"], "8.5")
    en.track_export(evening)
    assert en.supply_left() == 0
    hass.states.async_set(o["dispatch_power"], "10")
    assert await en.ev_guard(evening) == "trickle"
    # house load = pv + grid - batt = 0 - 1 + 9 = 8 kW total, EV 7.2, house 0.8 -> 7.2 + 0.8 + 0.2
    assert ("number", "set_value", {"entity_id": o["dispatch_power"], "value": 8.2}) in sent
    assert not any(x.get("option") == "Normal" for _, _, x in sent)
    assert "supply charge covered" in en.ev_guard_note and "200 W" in en.ev_guard_note
    hass.states.async_set(o["dispatch_power"], "8.2")
    assert await en.ev_guard(evening) == "ok"
    # EV not charging: guard stays out of the way
    hass.states.async_set(o["dispatch_mode"], "Force Discharge")
    hass.states.async_set(o["studio_ev"], "0", {"unit_of_measurement": "kW"})
    assert await en.ev_guard(evening) is None


async def test_health_skips_energy_counters_and_does_not_repeat(hass: HomeAssistant):
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass)
    pushes = []
    async def push(text, title="Cortex"):
        pushes.append(text)
        return True
    brain.speaker.push = push
    # a utility meter that inherited the battery device class must never count as a low battery
    hass.states.async_set("sensor.neovolt_online_pv_export_after_consumption", "9.2",
                          {"device_class": "battery", "unit_of_measurement": "%", "friendly_name": "Neovolt Online PV Export after consumption"})
    hass.states.async_set("sensor.door_battery", "9", {"device_class": "battery", "unit_of_measurement": "%", "friendly_name": "Door"})
    assert await brain.run_health() == ["Door battery at 9%"]
    assert len(pushes) == 1
    hass.states.async_set("sensor.door_battery", "8", {"device_class": "battery", "unit_of_measurement": "%", "friendly_name": "Door"})
    assert await brain.run_health() == ["Door battery at 8%"]
    assert len(pushes) == 1  # same issue, new number: no second alert


async def test_push_categories_can_be_muted_and_are_logged(hass: HomeAssistant):
    sent = async_mock_service(hass, "notify", "mobile_app_phone")
    entry_brain = await _setup(hass, notify="notify.mobile_app_phone", mute_push=["health"])
    sp = entry_brain.speaker
    assert sp.category("Cortex house health") == "health" and sp.category("Cortex autopilot") == "autopilot"
    assert await sp.push("Door battery at 9%", title="Cortex house health") is False
    assert await sp.push("Export started", title="Cortex energy") is True
    assert [p["category"] for p in sp.push_log] == ["energy", "health"]
    assert sp.push_log[1]["muted"] and sp.push_log[0]["sent"] and len(sent) == 1


async def test_ev_guard_keeps_battery_for_the_house(hass: HomeAssistant):
    """Supply charge not covered yet, but the house needs what's left: export only the trickle."""
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass)
    sent = []
    for domain, svc in (("number", "set_value"), ("select", "select_option"), ("button", "press")):
        async def rec(call, d=domain, s=svc):
            sent.append((d, s, dict(call.data)))
        hass.services.async_register(domain, svc, rec)
    o, en = brain.opts, brain.energy
    evening = dt_util.now().replace(hour=19, minute=0)
    en.house_kwh_day = 24.0
    hass.states.async_set(o["battery_soc"], "35")  # 7.5 kWh usable, house needs 15 kWh until 10:00
    hass.states.async_set(o["dispatch_mode"], "Force Discharge")
    hass.states.async_set(o["dispatch_power"], "7")
    hass.states.async_set(o["studio_ev"], "7.0", {"unit_of_measurement": "kW"})
    hass.states.async_set(o["studio_pv"], "0", {"unit_of_measurement": "kW"})
    hass.states.async_set(o["studio_grid"], "0", {"unit_of_measurement": "kW"})
    hass.states.async_set(o["studio_battery"], "8.0", {"unit_of_measurement": "kW"})
    assert en.supply_left() > 1
    assert await en.ev_guard(evening) == "trickle"
    assert ("number", "set_value", {"entity_id": o["dispatch_power"], "value": 8.2}) in sent
    assert "needed for the house" in en.ev_guard_note
    from unittest.mock import patch

    with patch("homeassistant.util.dt.now", return_value=evening):  # budget is judged at the clock time
        snap = en.snapshot()
    assert snap["budget"] and snap["budget"]["ok"] is False


async def test_planner_runs_publishes_and_autopilot_can_follow(hass: HomeAssistant, hass_ws_client):
    async_mock_service(hass, "notify", "send_message")
    brain = await _setup(hass, autopilot_mode="shadow", autopilot_planner=True)
    hass.states.async_set("sensor.neovolt_online_soc", "85")
    en = brain.energy
    load = [{"start": dt_util.utcnow() - timedelta(hours=h), "state": float(h % 24)} for h in range(96, 0, -1)]
    en.profile_from_stats(load, [])
    assert en.profile and len(en.profile) == 24
    plan = en.run_planner()
    assert plan and plan["summary"] and plan["follow"] and len(plan["rows"]) == 96
    brain.refresh()
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "cortex/overview"})
    res = (await ws.receive_json())["result"]
    assert res["plan"]["summary"] == plan["summary"] and res["control"]["use_planner"] is True
    d = await brain.autopilot.decide("topup", False)
    assert d["source"] == "plan" and "48-hour plan" in d["reason"]


async def test_same_notification_is_not_pushed_again(hass: HomeAssistant):
    sent = async_mock_service(hass, "notify", "mobile_app_phone")
    brain = await _setup(hass, notify="notify.mobile_app_phone")
    sp = brain.speaker
    assert await sp.push("Grid top-up started: solar short by 12.4 kWh.", title="Cortex energy")
    assert not await sp.push("Grid top-up started: solar short by 9.1 kWh.", title="Cortex energy")  # same message, new number
    assert sp.push_log[0]["repeat"] and len(sent) == 1
    assert await sp.push("Supply charge covered ($1.67 earned).", title="Cortex energy")
    assert len(sent) == 2


async def test_house_rule_guard(hass: HomeAssistant):
    """Outside the cheap window: forced export stops at the house's share; EV off-peak charges from the grid."""
    async_mock_service(hass, "notify", "send_message")
    sent = []
    for domain, svc in (("number", "set_value"), ("select", "select_option"), ("button", "press")):
        async def rec(call, d=domain, s=svc):
            sent.append((d, s, dict(call.data)))
            if d == "select":
                hass.states.async_set(call.data["entity_id"], call.data["option"])
        hass.services.async_register(domain, svc, rec)
    brain = await _setup(hass, autopilot_mode="auto")
    mode = LEGACY["dispatch_mode"]
    # 22:00 weekday (off-peak), house uses ~1 kWh/h until 10:00 = 12 kWh; battery 40% of 50 = 10 kWh usable
    now = datetime(2026, 11, 5, 22, 0, tzinfo=dt_util.get_default_time_zone())
    brain.energy.profile = [1.0] * 24
    hass.states.async_set(LEGACY["battery_soc"], "40")
    hass.states.async_set(mode, "Force Discharge")
    assert await brain.energy.house_guard(now) == "export_stopped"
    assert hass.states.get(mode).state == "Normal"
    # EV starts charging (7 kW) with the house at 1 kW: battery runs at house load, grid charges the car
    hass.states.async_set(LEGACY["studio_ev"], "7.0", {"unit_of_measurement": "kW"})
    hass.states.async_set(LEGACY["studio_pv"], "0", {"unit_of_measurement": "kW"})
    hass.states.async_set(LEGACY["studio_grid"], "7.0", {"unit_of_measurement": "kW"})
    hass.states.async_set(LEGACY["studio_battery"], "1000", {"unit_of_measurement": "W"})  # discharging 1 kW (this sensor reads + for discharge)
    sent.clear()
    assert await brain.energy.house_guard(now) == "house_only"
    assert hass.states.get(mode).state == "Force Discharge" and brain.energy.house_only
    assert ("number", "set_value", {"entity_id": LEGACY["dispatch_power"], "value": 1.2}) in sent  # 1 kW house + 200 W
    assert await brain.energy.ev_guard(now) is None  # EV-first does not take over
    # EV done: back to normal
    hass.states.async_set(LEGACY["studio_ev"], "0", {"unit_of_measurement": "kW"})
    assert await brain.energy.house_guard(now) == "ended" and hass.states.get(mode).state == "Normal"
    # inside the cheap window the rule does nothing
    assert await brain.energy.house_guard(now.replace(hour=11)) is None
