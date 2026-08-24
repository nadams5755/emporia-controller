from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_EVSE_ENTITIES, DOMAIN, ChargeMode
from .coordinator import EmporiaCoordinator

_LOGGER = logging.getLogger(__name__)

_MODES: list[tuple[str, str]] = [
    (ChargeMode.EXCESS_SOLAR, "Excess Solar Charge"),
    (ChargeMode.FULL_SPEED_OFFPEAK, "Off-Peak Full Speed Charge"),
    (ChargeMode.OVERRIDE, "Full Speed Charge Now"),
]

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
        EvseModeSwitch(coordinator, evse, mode, label, _evse_friendly_name(hass, evse))
        for evse in entry.data[CONF_EVSE_ENTITIES]
        for mode, label in _MODES
    ]
    async_add_entities(entities)
    _remove_stale_switches(hass, entry, {e._attr_unique_id for e in entities})

def _remove_stale_switches(hass: HomeAssistant, entry: ConfigEntry, valid_unique_ids: set[str]) -> None:
    """Remove switch entities left behind by a retired mode (e.g. "stopped").

    HA doesn't drop entities from the registry just because a platform stops
    returning them, so without this a removed mode's switch lingers forever.
    """
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain == "switch" and reg_entry.unique_id not in valid_unique_ids:
            _LOGGER.info("Removing stale switch entity from a retired mode: %s", reg_entry.entity_id)
            registry.async_remove(reg_entry.entity_id)

class EvseModeSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(
        self,
        coordinator: EmporiaCoordinator,
        evse_entity: str,
        mode: str,
        label: str,
        evse_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._evse_entity = evse_entity
        self._mode = mode
        evse_slug = evse_entity.replace(".", "_")
        self._attr_name = f"{evse_name} - {label}"
        self._attr_unique_id = f"{DOMAIN}_{evse_slug}_{mode}"

    @property
    def is_on(self) -> bool:
        return self.coordinator.get_mode(self._evse_entity) == self._mode

    async def async_turn_on(self, **kwargs) -> None:  # pylint: disable=unused-argument
        _LOGGER.info("Mode selected: '%s' for %s", self._attr_name, self._evse_entity)
        await self.coordinator.set_mode(self._evse_entity, self._mode)

    async def async_turn_off(self, **kwargs) -> None:  # pylint: disable=unused-argument
        pass
