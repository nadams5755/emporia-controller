"""
Stub out homeassistant so tests run without installing the full HA stack.
This module must execute before any test file imports custom_components.
"""
import sys
from unittest.mock import MagicMock

class _DataUpdateCoordinator:
    """Minimal DataUpdateCoordinator stub that satisfies EmporiaCoordinator's super().__init__."""

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval

    # Support DataUpdateCoordinator[dict] generic syntax at class-definition time.
    def __class_getitem__(cls, item):  # pylint: disable=unused-argument
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

class _CoordinatorEntity:
    _attr_name: str = ""
    _attr_unique_id: str = ""

    def __init__(self, coordinator):
        self.coordinator = coordinator

class _SwitchEntity:
    _attr_name: str = ""
    _attr_unique_id: str = ""

class _SensorEntity:
    _attr_name: str = ""
    _attr_unique_id: str = ""

def _install_stubs() -> None:
    update_coordinator = MagicMock()
    update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
    update_coordinator.UpdateFailed = _UpdateFailed
    update_coordinator.CoordinatorEntity = _CoordinatorEntity

    storage = MagicMock()
    storage.Store = _Store

    entity_registry = MagicMock()

    helpers = MagicMock()
    helpers.entity_registry = entity_registry

    switch_mod = MagicMock()
    switch_mod.SwitchEntity = _SwitchEntity

    sensor_mod = MagicMock()
    sensor_mod.SensorEntity = _SensorEntity

    dt_mod = MagicMock()

    sys.modules.update(
        {
            "homeassistant": MagicMock(),
            "homeassistant.config_entries": MagicMock(),
            "homeassistant.core": MagicMock(),
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.storage": storage,
            "homeassistant.helpers.update_coordinator": update_coordinator,
            "homeassistant.helpers.entity_platform": MagicMock(),
            "homeassistant.helpers.entity_registry": entity_registry,
            "homeassistant.util": MagicMock(),
            "homeassistant.util.dt": dt_mod,
            "homeassistant.components": MagicMock(),
            "homeassistant.components.switch": switch_mod,
            "homeassistant.components.sensor": sensor_mod,
        }
    )

_install_stubs()
