from datetime import date, datetime, timedelta, timezone

from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.cortex.const import DEFAULTS, DOMAIN
from custom_components.cortex.learning import detect_chains, detect_routines, service_for
from custom_components.cortex.heating import lead_minutes
from custom_components.cortex.visitors import parse_look

UTC = timezone.utc


async def _setup(hass: HomeAssistant, **opts):
    entry = MockConfigEntry(domain=DOMAIN, title="Cortex", data={}, options={**DEFAULTS, **opts})
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
    sid = brain.learning.pending[0]["id"]
    routine = await hass.services.async_call(
        DOMAIN, "accept_suggestion", {"id": sid}, blocking=True, return_response=True
    )
    assert routine["routine"]["name"] in brain.routines.items
    assert hass.states.get("sensor.cortex_routine_suggestions").state == "0"


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
