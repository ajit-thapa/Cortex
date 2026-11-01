"""Cortex: a shared brain for voice, memory, safety and home energy."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .const import DOMAIN
from .llm_api import CortexAPI
from .runtime import Cortex
from .services import async_register_services, async_unregister_services
from .websocket import async_register_websocket

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]
PANEL_URL = "cortex"
STUDIO_URL = "cortex-studio"
FRONTEND_PATH = f"/{DOMAIN}_static"
FRONTEND_VERSION = "0.8.1"  # cache-buster for the panel scripts


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    async_register_services(hass)
    async_register_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    brain = Cortex(hass, entry)
    await brain.async_start()
    hass.data[DOMAIN][entry.entry_id] = brain

    entry.async_on_unload(
        llm.async_register_api(hass, CortexAPI(hass, brain))
    )
    await _async_register_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        brain: Cortex = hass.data[DOMAIN].pop(entry.entry_id)
        brain.async_stop()
        if not hass.data[DOMAIN]:
            async_unregister_services(hass)
            try:
                from homeassistant.components import frontend

                frontend.async_remove_panel(hass, PANEL_URL)
                frontend.async_remove_panel(hass, STUDIO_URL)
            except Exception:  # noqa: BLE001 - panel may never have been registered
                pass
            hass.data.pop(f"{DOMAIN}_panel", None)
    return ok


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_panel(hass: HomeAssistant) -> None:
    if hass.data.get(f"{DOMAIN}_panel"):
        return
    try:
        from homeassistant.components import panel_custom
        from homeassistant.components.http import StaticPathConfig

        folder = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_PATH, str(folder), False)]
        )
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name="cortex-panel",
            frontend_url_path=PANEL_URL,
            module_url=f"{FRONTEND_PATH}/cortex-panel.js?v={FRONTEND_VERSION}",
            sidebar_title="Cortex",
            sidebar_icon="mdi:brain",
            require_admin=False,
        )
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name="cortex-studio",
            frontend_url_path=STUDIO_URL,
            module_url=f"{FRONTEND_PATH}/cortex-studio.js?v={FRONTEND_VERSION}",
            sidebar_title="Energy Studio",
            sidebar_icon="mdi:lightning-bolt-circle",
            require_admin=False,
        )
        hass.data[f"{DOMAIN}_panel"] = True
    except Exception as err:  # noqa: BLE001 - the panel is optional
        _LOGGER.warning("Cortex panel not registered: %s", err)
