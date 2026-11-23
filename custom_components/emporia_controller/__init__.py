from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import EmporiaCoordinator

PLATFORMS = ["switch", "sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = EmporiaCoordinator(hass, entry)
    await coordinator.async_load_state()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reload when options change so reconfigured values (e.g. super off-peak hours)
    # take effect without restarting Home Assistant.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Go through HA's config-entry machinery rather than calling unload/setup directly:
    # setup must run inside the config entry's context or the coordinator's first
    # refresh raises ConfigEntryError and leaves the entry half-loaded.
    await hass.config_entries.async_reload(entry.entry_id)
