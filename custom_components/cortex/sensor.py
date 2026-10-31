"""Cortex sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATE
from .runtime import Cortex

KWH = UnitOfEnergy.KILO_WATT_HOUR


@dataclass(frozen=True, kw_only=True)
class CortexSensorDescription(SensorEntityDescription):
    value: Callable[[Cortex], Any]
    attrs: Callable[[Cortex], dict[str, Any]] | None = None


def _e(key: str) -> Callable[[Cortex], Any]:
    return lambda b: b.snapshot.get(key)


def _storage(key: str) -> dict[str, Any]:
    return dict(
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    )


SENSORS: tuple[CortexSensorDescription, ...] = (
    CortexSensorDescription(
        key="period", translation_key="period", icon="mdi:clock-time-four-outline",
        device_class=SensorDeviceClass.ENUM, options=["peak", "shoulder", "off_peak"],
        value=_e("period"),
        attrs=lambda b: {"business_day": b.snapshot.get("business_day"), "high_season": b.snapshot.get("high_season")},
    ),
    CortexSensorDescription(
        key="import_rate", translation_key="import_rate", icon="mdi:transmission-tower-import",
        native_unit_of_measurement="c/kWh", state_class=SensorStateClass.MEASUREMENT, value=_e("import_rate"),
    ),
    CortexSensorDescription(
        key="feed_in_rate", translation_key="feed_in_rate", icon="mdi:transmission-tower-export",
        native_unit_of_measurement="c/kWh", state_class=SensorStateClass.MEASUREMENT, value=_e("feed_in_rate"),
    ),
    CortexSensorDescription(
        key="next_period", translation_key="next_period", icon="mdi:calendar-arrow-right",
        device_class=SensorDeviceClass.ENUM, options=["peak", "shoulder", "off_peak"], value=_e("next_period"),
    ),
    CortexSensorDescription(
        key="next_change", translation_key="next_change", device_class=SensorDeviceClass.TIMESTAMP,
        value=_e("next_change"),
    ),
    CortexSensorDescription(
        key="export_to_cover", translation_key="export_to_cover", icon="mdi:cash-check",
        native_unit_of_measurement=KWH, suggested_display_precision=2, value=_e("export_to_cover"),
    ),
    CortexSensorDescription(
        key="pv_shortfall", translation_key="pv_shortfall", icon="mdi:weather-sunny-alert",
        native_unit_of_measurement=KWH, suggested_display_precision=1, value=_e("pv_shortfall"),
    ),
    CortexSensorDescription(
        key="solar_day", translation_key="solar_day", icon="mdi:weather-sunny",
        device_class=SensorDeviceClass.ENUM, options=["low", "ok", "unknown"], value=_e("solar_day"),
    ),
    CortexSensorDescription(key="battery_stored", translation_key="battery_stored", value=_e("battery_stored"), **_storage("b")),
    CortexSensorDescription(key="battery_usable", translation_key="battery_usable", value=_e("battery_usable"), **_storage("u")),
    CortexSensorDescription(key="battery_room", translation_key="battery_room", value=_e("battery_room"), **_storage("r")),
    CortexSensorDescription(key="ev_stored", translation_key="ev_stored", value=_e("ev_stored"), **_storage("e")),
    CortexSensorDescription(key="ev_room", translation_key="ev_room", value=_e("ev_room"), **_storage("er")),
    CortexSensorDescription(
        key="storage_summary", translation_key="storage_summary", icon="mdi:battery-charging-wireless",
        value=_e("storage_summary"),
    ),
    CortexSensorDescription(
        key="summary", translation_key="summary", icon="mdi:text-box-outline", value=_e("summary"),
    ),
    CortexSensorDescription(
        key="memories", translation_key="memories", icon="mdi:head-cog-outline",
        state_class=SensorStateClass.MEASUREMENT, value=lambda b: len(b.book.items),
        attrs=lambda b: {"recent": [m.text for m in b.book.recall("", 10)]},
    ),
    CortexSensorDescription(
        key="last_spoken", translation_key="last_spoken", icon="mdi:message-text-outline",
        value=lambda b: (b.speaker.log[0]["text"][:255] if b.speaker.log else None),
        attrs=lambda b: {"log": list(b.speaker.log)[:10]},
    ),
    CortexSensorDescription(
        key="likely_room", translation_key="likely_room", icon="mdi:map-marker-radius",
        value=lambda b: b.speaker.likely_area(),
    ),
    CortexSensorDescription(
        key="health_issues", translation_key="health_issues", icon="mdi:heart-pulse",
        state_class=SensorStateClass.MEASUREMENT, value=lambda b: len(b.health),
        attrs=lambda b: {"issues": b.health},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    brain: Cortex = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CortexSensor(brain, entry, d) for d in SENSORS)


class CortexSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: CortexSensorDescription

    def __init__(self, brain: Cortex, entry: ConfigEntry, desc: CortexSensorDescription) -> None:
        self.brain = brain
        self.entity_description = desc
        self._attr_unique_id = f"{entry.entry_id}_{desc.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer="Cortex",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL_UPDATE}_{self.brain.entry.entry_id}", self._changed
            )
        )

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value(self.brain)
        if isinstance(value, datetime):
            return value
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs
        return fn(self.brain) if fn else None
