from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_EVSE_ENTITIES, DOMAIN
from .coordinator import EmporiaCoordinator

_LOGGER = logging.getLogger(__name__)


def _evse_friendly_name(hass: HomeAssistant, evse_entity: str) -> str:
    state = hass.states.get(evse_entity)
    if state and (name := state.attributes.get("friendly_name")):
        return name
    return evse_entity.split(".", 1)[-1].replace("_", " ").title()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmporiaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        EvseStatusSensor(coordinator, evse, _evse_friendly_name(hass, evse))
        for evse in entry.data[CONF_EVSE_ENTITIES]
    ]
    async_add_entities(entities)


class EvseStatusSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator: EmporiaCoordinator,
        evse_entity: str,
        evse_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._evse_entity = evse_entity
        evse_slug = evse_entity.replace(".", "_")
        self._attr_name = f"{evse_name} - Status"
        self._attr_unique_id = f"{DOMAIN}_{evse_slug}_status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        target = data.get("targets", {}).get(self._evse_entity)
        if target:
            return "charging"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        target_amps = data.get("targets", {}).get(self._evse_entity)
        target_kw = round(target_amps * self.coordinator.voltage / 1000, 2) if target_amps else None
        attrs: dict = {
            "mode": self.coordinator.get_mode(self._evse_entity),
            "target_amps": target_amps,
            "target_kw": target_kw,
            "export_watts": data.get("export_watts"),
            "available_watts": data.get("available_watts"),
            "powerwall_discharging": data.get("powerwall_discharging"),
        }
        if reason := data.get("skip_reasons", {}).get(self._evse_entity):
            attrs["skip_reason"] = reason
        return attrs
