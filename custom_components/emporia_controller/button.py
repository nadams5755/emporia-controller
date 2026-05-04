from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_EVSE_ENTITIES, DOMAIN, ChargeMode
from .coordinator import EmporiaCoordinator

_LOGGER = logging.getLogger(__name__)

_BUTTONS: list[tuple[str, str]] = [
    (ChargeMode.EXCESS_SOLAR, "Charge on Excess Solar"),
    (ChargeMode.FULL_SPEED_OFFPEAK, "Charge Full Speed Off-Peak"),
    (ChargeMode.OVERRIDE, "Charge Full Speed Now"),
    (ChargeMode.STOPPED, "Stop Charging"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EmporiaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        EvseModeButton(coordinator, evse, mode, label)
        for evse in entry.data[CONF_EVSE_ENTITIES]
        for mode, label in _BUTTONS
    ]
    async_add_entities(entities)


class EvseModeButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EmporiaCoordinator,
        evse_entity: str,
        mode: str,
        label: str,
    ) -> None:
        self._coordinator = coordinator
        self._evse_entity = evse_entity
        self._mode = mode
        evse_slug = evse_entity.replace(".", "_")
        self._attr_name = label
        self._attr_unique_id = f"{DOMAIN}_{evse_slug}_{mode}"

    async def async_press(self) -> None:
        _LOGGER.info("Button pressed: '%s' for %s", self._attr_name, self._evse_entity)
        await self._coordinator.set_mode(self._evse_entity, self._mode)
