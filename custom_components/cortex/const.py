"""Constants and option defaults for Cortex."""

from __future__ import annotations

DOMAIN = "cortex"
STORAGE_VERSION = 1
SIGNAL_UPDATE = f"{DOMAIN}_update"
EVENT_SPOKEN = f"{DOMAIN}_spoken"

# --- general ---------------------------------------------------------------
CONF_SPEAKERS = "speakers"
CONF_TTS_ENGINE = "tts_engine"
CONF_NOTIFY = "notify"
CONF_MOTION = "motion_sensors"
CONF_QUIET_START = "quiet_start"
CONF_QUIET_END = "quiet_end"
CONF_BANNED = "banned_words"
CONF_DEDUPE = "dedupe_minutes"
CONF_AGENT = "conversation_agent"

# --- briefing, reports, AI -------------------------------------------------
CONF_BRIEF_MORNING = "briefing_morning"
CONF_BRIEF_EVENING = "briefing_evening"
CONF_BRIEF_SECTIONS = "briefing_sections"
CONF_BRIEF_AI = "briefing_ai"
CONF_WEATHER = "weather_entity"
CONF_WEEKLY_TIME = "weekly_time"
CONF_AUTO_BACKUP = "auto_backup"
CONF_AI_TASK = "ai_task"
CONF_AI_PER_HOUR = "ai_per_hour"

# --- security, visitors, learning ------------------------------------------
CONF_NIGHT_WATCH = "night_watch"
CONF_NIGHT_START = "night_start"
CONF_NIGHT_END = "night_end"
CONF_DOORBELL = "doorbell_entities"
CONF_DOORBELL_CAMERA = "doorbell_camera"
CONF_LEARN = "learn_entities"

# Energy Studio panel: live power sources and daily energy totals
CONF_ST_PV = "studio_pv"
CONF_ST_GRID = "studio_grid"
CONF_ST_BATT = "studio_battery"
CONF_ST_EV = "studio_ev"
CONF_ST_GRID_INVERT = "studio_grid_invert"
CONF_ST_BATT_INVERT = "studio_battery_invert"
CONF_ST_DAY_PV = "studio_day_pv"
CONF_ST_DAY_LOAD = "studio_day_load"
CONF_ST_DAY_EXPORT = "studio_day_export"
CONF_ST_DAY_IMPORT = "studio_day_import"

BRIEF_SECTIONS = ["energy", "weather", "reminders", "health", "security", "parcels"]

# --- energy entities -------------------------------------------------------
CONF_SOC = "battery_soc"
CONF_MODE = "dispatch_mode"
CONF_POWER = "dispatch_power"
CONF_DURATION = "dispatch_duration"
CONF_CHARGE_TARGET = "charge_target"
CONF_DISCHARGE_TARGET = "discharge_target"
CONF_STOP = "stop_button"
CONF_PV_TODAY = "pv_forecast_today"
CONF_PV_TOMORROW = "pv_forecast_tomorrow"
CONF_EV_SOC = "ev_soc"
CONF_EV_PLUG = "ev_plug"
CONF_EV_TARGET = "ev_target_soc"
CONF_EV_START = "ev_start_button"
CONF_HOLIDAYS = "holiday_calendar"

# --- energy numbers / switches --------------------------------------------
CONF_BATTERY_KWH = "battery_kwh"
CONF_EV_KWH = "ev_kwh"
CONF_RESERVE = "battery_reserve_pct"
CONF_LOW_SOLAR = "low_solar_kwh"
CONF_TOPUP_KW = "topup_kw"
CONF_EXPORT_KW = "export_kw"
CONF_EXPORT_MIN_SOC = "export_min_soc"
CONF_EXPORT_FLOOR = "export_floor_soc"
CONF_AUTO_TOPUP = "auto_topup"
CONF_AUTO_EXPORT = "auto_export"
CONF_EV_GATE = "ev_gate"
CONF_EV_WINDOW = "ev_window"

# --- tariff ---------------------------------------------------------------
CONF_RATE_HIGH_PEAK = "rate_high_peak"
CONF_RATE_LOW_PEAK = "rate_low_peak"
CONF_RATE_SHOULDER = "rate_shoulder"
CONF_RATE_OFF_PEAK = "rate_off_peak"
CONF_SUPPLY = "supply_charge"
CONF_FIT_EVENING = "fit_evening"
CONF_FIT_MORNING = "fit_morning"
CONF_FIT_OTHER = "fit_other"

DEFAULTS: dict[str, object] = {
    CONF_SPEAKERS: [],
    CONF_MOTION: [],
    CONF_BRIEF_MORNING: "07:30:00",
    CONF_BRIEF_EVENING: None,
    CONF_BRIEF_SECTIONS: ["energy", "weather", "reminders", "health", "security", "parcels"],
    CONF_BRIEF_AI: False,
    CONF_WEATHER: None,
    CONF_WEEKLY_TIME: "18:00:00",
    CONF_AUTO_BACKUP: True,
    CONF_AI_TASK: None,
    CONF_AI_PER_HOUR: 12,
    CONF_NIGHT_WATCH: True,
    CONF_NIGHT_START: "23:00:00",
    CONF_NIGHT_END: "06:00:00",
    CONF_DOORBELL: [],
    CONF_DOORBELL_CAMERA: None,
    CONF_LEARN: [],
    CONF_ST_PV: "sensor.sungrow_pv",
    CONF_ST_GRID: "sensor.neovolt_online_grid",
    CONF_ST_BATT: "sensor.neovolt_online_battery_power",
    CONF_ST_EV: "sensor.tesla_wall_connector_ev_charger",
    CONF_ST_GRID_INVERT: False,
    CONF_ST_BATT_INVERT: False,
    CONF_ST_DAY_PV: "sensor.neovolt_online_pv_generated_today",
    CONF_ST_DAY_LOAD: "sensor.neovolt_online_consumed_today",
    CONF_ST_DAY_EXPORT: "sensor.neovolt_online_feed_in_today",
    CONF_ST_DAY_IMPORT: "sensor.neovolt_online_grid_import_today",
    CONF_QUIET_START: "22:00:00",
    CONF_QUIET_END: "07:00:00",
    CONF_BANNED: "",
    CONF_DEDUPE: 30,
    CONF_NOTIFY: "notify.iphone_2",
    CONF_SOC: "sensor.neovolt_online_soc",
    CONF_MODE: "select.neovolt_neovoltlocal_dispatch_mode",
    CONF_POWER: "number.neovolt_neovoltlocal_dispatch_power",
    CONF_DURATION: "number.neovolt_neovoltlocal_dispatch_duration",
    CONF_CHARGE_TARGET: "number.neovolt_neovoltlocal_dispatch_charge_target_soc",
    CONF_DISCHARGE_TARGET: "number.neovolt_neovoltlocal_dispatch_discharge_target_soc",
    CONF_STOP: "button.neovolt_neovoltlocal_stop_force_charge_discharge",
    CONF_PV_TODAY: "sensor.pv_forecast_ingleburn",
    CONF_PV_TOMORROW: "sensor.pv_forecast_forecast",
    CONF_EV_SOC: "sensor.byd_sealion_7_battery_level",
    CONF_EV_PLUG: "binary_sensor.byd_sealion_7_plug",
    CONF_EV_TARGET: "input_number.byd_target_soc",
    CONF_EV_START: "button.byd_sealion_7_start_charging",
    CONF_HOLIDAYS: "calendar.australia_nsw",
    CONF_BATTERY_KWH: 50.0,
    CONF_EV_KWH: 82.5,
    CONF_RESERVE: 20.0,
    CONF_LOW_SOLAR: 30.0,
    CONF_TOPUP_KW: 5.0,
    CONF_EXPORT_KW: 7.0,
    CONF_EXPORT_MIN_SOC: 35.0,
    CONF_EXPORT_FLOOR: 30.0,
    CONF_AUTO_TOPUP: False,
    CONF_AUTO_EXPORT: False,
    CONF_EV_GATE: False,
    CONF_RATE_HIGH_PEAK: 41.91,
    CONF_RATE_LOW_PEAK: 42.416,
    CONF_RATE_SHOULDER: 11.11,
    CONF_RATE_OFF_PEAK: 32.12,
    CONF_SUPPLY: 166.617,
    CONF_FIT_EVENING: 28.0,
    CONF_FIT_MORNING: 3.0,
    CONF_FIT_OTHER: 3.0,
}

SAFETY_CLASSES = {
    "smoke": "has detected smoke",
    "carbon_monoxide": "has detected carbon monoxide",
    "gas": "has detected gas",
    "moisture": "has detected water",
    "tamper": "has been tampered with",
    "safety": "has raised a safety alert",
}
