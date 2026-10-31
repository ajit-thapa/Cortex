from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.cortex.const import DEFAULTS, DOMAIN


async def _setup(hass: HomeAssistant, **opts):
    entry = MockConfigEntry(domain=DOMAIN, title="Cortex", data={}, options={**DEFAULTS, **opts})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_and_energy_sensors(hass: HomeAssistant):
    hass.states.async_set("sensor.neovolt_online_soc", "54")
    hass.states.async_set("sensor.pv_forecast_ingleburn", "42.2")
    hass.states.async_set("sensor.byd_sealion_7_battery_level", "40")
    entry = await _setup(hass)
    assert entry.state.value == "loaded"
    brain = hass.data[DOMAIN][entry.entry_id]
    brain.refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.cortex_battery_stored")
    assert state is not None and float(state.state) == 27.0
    assert float(hass.states.get("sensor.cortex_battery_room_left").state) == 23.0
    assert float(hass.states.get("sensor.cortex_ev_room_left").state) == 49.5
    assert hass.states.get("sensor.cortex_solar_day").state == "ok"
    assert hass.states.get("sensor.cortex_tariff_period").state in ("peak", "shoulder", "off_peak")
    assert "Battery 27.0/50 kWh" in hass.states.get("sensor.cortex_storage_summary").state


async def test_memory_services_and_llm_api(hass: HomeAssistant):
    await _setup(hass)
    res = await hass.services.async_call(
        DOMAIN, "remember", {"text": "The rabbits live by the shed", "category": "place"},
        blocking=True, return_response=True,
    )
    assert res["text"].startswith("The rabbits")
    found = await hass.services.async_call(
        DOMAIN, "recall", {"query": "rabbit"}, blocking=True, return_response=True
    )
    assert len(found["memories"]) == 1
    assert hass.states.get("sensor.cortex_memories").state == "1"
    api = await llm.async_get_api(
        hass, DOMAIN,
        llm.LLMContext(platform="test", context=None, language="en", assistant=None, device_id=None),
    )
    assert {t.name for t in api.tools} >= {"remember", "recall", "energy_status"}


async def test_say_respects_quiet_hours_and_speaks(hass: HomeAssistant):
    calls = async_mock_service(hass, "assist_satellite", "announce")
    await _setup(hass, speakers=["assist_satellite.kitchen"], quiet_start="00:00:00", quiet_end="00:00:00")
    rec = await hass.services.async_call(
        DOMAIN, "say", {"message": "Dinner is ready"}, blocking=True, return_response=True
    )
    assert rec["spoken"] and len(calls) == 1
    again = await hass.services.async_call(
        DOMAIN, "say", {"message": "Dinner is ready"}, blocking=True, return_response=True
    )
    assert again["reason"] == "duplicate" and len(calls) == 1


async def test_safety_alarm_is_urgent(hass: HomeAssistant):
    calls = async_mock_service(hass, "assist_satellite", "announce")
    hass.states.async_set("binary_sensor.kitchen_smoke", "off", {"device_class": "smoke", "friendly_name": "Kitchen smoke"})
    await _setup(hass, speakers=["assist_satellite.kitchen"], quiet_start="00:00:01", quiet_end="23:59:59", notify="")
    hass.states.async_set("binary_sensor.kitchen_smoke", "on", {"device_class": "smoke", "friendly_name": "Kitchen smoke"})
    await hass.async_block_till_done()
    assert len(calls) == 1 and "smoke" in calls[0].data["message"]


async def test_reminder_and_unload(hass: HomeAssistant):
    entry = await _setup(hass)
    res = await hass.services.async_call(
        DOMAIN, "remind", {"message": "Bins out", "in_minutes": 5}, blocking=True, return_response=True
    )
    brain = hass.data[DOMAIN][entry.entry_id]
    assert len(brain.reminders) == 1 and res["id"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, "say")


async def test_topup_runs_when_short(hass: HomeAssistant):
    modes = async_mock_service(hass, "select", "select_option")
    async_mock_service(hass, "number", "set_value")
    hass.states.async_set("sensor.neovolt_online_soc", "20")
    hass.states.async_set("sensor.pv_forecast_ingleburn", "10")
    entry = await _setup(hass, notify="")
    brain = hass.data[DOMAIN][entry.entry_id]
    assert await brain.energy.start_topup() == "started"
    assert modes[0].data["option"] == "Force Charge"
    hass.states.async_set("sensor.pv_forecast_ingleburn", "60")
    assert (await brain.energy.start_topup()).startswith("skipped")


async def test_options_flow(hass: HomeAssistant):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tariff"})
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"fit_evening": 30.0})
    assert result["type"] == "create_entry"
    assert entry.options["fit_evening"] == 30.0


async def test_sensors_fill_when_sources_appear_after_start(hass: HomeAssistant):
    entry = await _setup(hass)  # nothing exists yet, like a restart race
    assert hass.states.get("sensor.cortex_battery_stored").state == "unknown"
    hass.states.async_set("sensor.neovolt_online_soc", "50")
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.cortex_battery_stored").state) == 25.0
    assert hass.states.get(f"sensor.cortex_storage_summary").state.startswith("Battery 25.0/50")
