"""
Stub out homeassistant so tests run without installing the full HA stack.
This module must execute before any test file imports custom_components.
"""
import sys
from unittest.mock import AsyncMock, MagicMock


class _DataUpdateCoordinator:
    """Minimal DataUpdateCoordinator stub that satisfies EmporiaCoordinator's super().__init__."""

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval

    # Support DataUpdateCoordinator[dict] generic syntax at class-definition time.
    def __class_getitem__(cls, item):
        return cls

    async def async_request_refresh(self):
        pass


class _UpdateFailed(Exception):
    pass


class _Store:
    def __init__(self, hass, version, key):
        pass

    async def async_load(self):
        return None

    async def async_save(self, data):
        pass


class _ButtonEntity:
    _attr_name: str = ""
    _attr_unique_id: str = ""


def _install_stubs() -> None:
    update_coordinator = MagicMock()
    update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
    update_coordinator.UpdateFailed = _UpdateFailed

    storage = MagicMock()
    storage.Store = _Store

    button_mod = MagicMock()
    button_mod.ButtonEntity = _ButtonEntity

    dt_mod = MagicMock()

    sys.modules.update(
        {
            "homeassistant": MagicMock(),
            "homeassistant.config_entries": MagicMock(),
            "homeassistant.core": MagicMock(),
            "homeassistant.helpers": MagicMock(),
            "homeassistant.helpers.storage": storage,
            "homeassistant.helpers.update_coordinator": update_coordinator,
            "homeassistant.helpers.entity_platform": MagicMock(),
            "homeassistant.util": MagicMock(),
            "homeassistant.util.dt": dt_mod,
            "homeassistant.components": MagicMock(),
            "homeassistant.components.button": button_mod,
        }
    )


_install_stubs()
