from unittest.mock import AsyncMock, MagicMock

from custom_components.emporia_controller import async_reload_entry, async_unload_entry
from custom_components.emporia_controller.const import DOMAIN


async def test_reload_entry_delegates_to_config_entries_reload():
    """Options-change reload must go through HA so setup runs in the config entry's context."""
    hass = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    entry = MagicMock()
    entry.entry_id = "entry1"
    await async_reload_entry(hass, entry)
    hass.config_entries.async_reload.assert_awaited_once_with("entry1")


async def test_unload_entry_tolerates_missing_coordinator():
    """Unloading an entry whose setup failed must not raise KeyError."""
    hass = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.data = {DOMAIN: {}}
    entry = MagicMock()
    entry.entry_id = "entry1"
    assert await async_unload_entry(hass, entry) is True


async def test_unload_entry_removes_coordinator():
    hass = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.data = {DOMAIN: {"entry1": object()}}
    entry = MagicMock()
    entry.entry_id = "entry1"
    await async_unload_entry(hass, entry)
    assert "entry1" not in hass.data[DOMAIN]
