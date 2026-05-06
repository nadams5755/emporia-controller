from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_EVSE_ENTITIES, DOMAIN, ChargeMode
from .coordinator import EmporiaCoordinator

_LOGGER = logging.getLogger(__name__)

_MODES: list[tuple[str, str]] = [
    (ChargeMode.EXCESS_SOLAR, "Excess Solar Charge"),
    (ChargeMode.FULL_SPEED_OFFPEAK, "Off-Peak Full Speed Charge"),
    (ChargeMode.OVERRIDE, "Full Speed Charge Now"),
    (ChargeMode.STOPPED, "Stop Charging"),
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

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("Mode selected: '%s' for %s", self._attr_name, self._evse_entity)
        await self.coordinator.set_mode(self._evse_entity, self._mode)

    async def async_turn_off(self, **kwargs) -> None:
        pass
