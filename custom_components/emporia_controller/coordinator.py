from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    BATTERY_DISCHARGE_THRESHOLD_KW,
    CHARGING_WINDOW_END_HOUR,
    CHARGING_WINDOW_START_HOUR,
    CONF_BATTERY_POWER_SENSOR,
    CONF_EVSE_ENTITIES,
    CONF_SITE_POWER_SENSOR,
    CONF_VOLTAGE,
    DEFAULT_MAX_AMPS,
    DEFAULT_VOLTAGE,
    DOMAIN,
    MIN_CHARGE_AMPS,
    OFFPEAK_END_HOUR,
    STORAGE_KEY,
    STORAGE_VERSION,
    UPDATE_INTERVAL_SECONDS,
    ChargeMode,
)

_LOGGER = logging.getLogger(__name__)


class EmporiaCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self._entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._evse_modes: dict[str, str] = {}
        config = {**entry.data, **entry.options}
        self._evse_entities: list[str] = config[CONF_EVSE_ENTITIES]
        self._site_power_sensor: str = config[CONF_SITE_POWER_SENSOR]
        self._battery_power_sensor: str = config[CONF_BATTERY_POWER_SENSOR]
        self._voltage: int = config.get(CONF_VOLTAGE, DEFAULT_VOLTAGE)
        self._last_targets: dict[str, int] = {}

    async def async_load_state(self) -> None:
        data = await self._store.async_load()
        if data:
            self._evse_modes = data.get("evse_modes", {})
        for evse in self._evse_entities:
            self._evse_modes.setdefault(evse, ChargeMode.EXCESS_SOLAR)

    async def _save_state(self) -> None:
        await self._store.async_save({"evse_modes": self._evse_modes})

    def get_mode(self, evse_entity: str) -> str:
        return self._evse_modes.get(evse_entity, ChargeMode.EXCESS_SOLAR)

    async def set_mode(self, evse_entity: str, mode: str) -> None:
        old_mode = self._evse_modes.get(evse_entity, ChargeMode.EXCESS_SOLAR)
        self._evse_modes[evse_entity] = mode
        _LOGGER.info("%s mode changed: %s → %s", evse_entity, old_mode, mode)
        await self._save_state()
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict:
        try:
            return await self._run_control_loop()
        except Exception as err:
            raise UpdateFailed(f"Control loop error: {err}") from err

    async def _run_control_loop(self) -> dict:
        now = dt_util.now()
        hour = now.hour
        in_charging_window = CHARGING_WINDOW_START_HOUR <= hour < CHARGING_WINDOW_END_HOUR
        in_offpeak = CHARGING_WINDOW_START_HOUR <= hour < OFFPEAK_END_HOUR

        powerwall_discharging = self._is_powerwall_discharging()
        export_watts = self._get_export_watts()

        targets: dict[str, int] = {}
        solar_evses: list[str] = []

        for evse in self._evse_entities:
            mode = self._evse_modes.get(evse, ChargeMode.EXCESS_SOLAR)

            if mode == ChargeMode.STOPPED:
                targets[evse] = 0

            elif mode == ChargeMode.OVERRIDE:
                targets[evse] = self._get_max_amps(evse)

            elif mode == ChargeMode.FULL_SPEED_OFFPEAK:
                if in_offpeak and not powerwall_discharging:
                    targets[evse] = self._get_max_amps(evse)
                else:
                    targets[evse] = 0

            elif mode == ChargeMode.EXCESS_SOLAR:
                if in_charging_window and not powerwall_discharging and export_watts > 0 and self._has_vehicle_connected(evse):
                    solar_evses.append(evse)
                else:
                    targets[evse] = 0

        if solar_evses:
            targets.update(self._allocate_solar_current(solar_evses, export_watts))

        for evse, amps in targets.items():
            await self._set_evse_current(evse, amps)

        return {
            "targets": targets,
            "powerwall_discharging": powerwall_discharging,
            "export_watts": export_watts,
        }

    def _allocate_solar_current(self, evses: list[str], export_watts: float) -> dict[str, int]:
        available_amps = int(export_watts / self._voltage)
        per_evse = available_amps // len(evses)

        if per_evse < MIN_CHARGE_AMPS:
            return {evse: 0 for evse in evses}

        return {evse: per_evse for evse in evses}

    def _has_vehicle_connected(self, evse_entity: str) -> bool:
        state = self.hass.states.get(evse_entity)
        if state is None:
            return False
        icon = state.attributes.get("icon_name")
        # Default to True if attribute is absent (assume connected)
        return icon is None or icon != "CarNotConnected"

    def _is_powerwall_discharging(self) -> bool:
        # battery_power in kW; positive = discharging (outputting to home/grid)
        state = self.hass.states.get(self._battery_power_sensor)
        if state is None:
            _LOGGER.warning("Battery power sensor %s unavailable", self._battery_power_sensor)
            return False
        try:
            return float(state.state) > BATTERY_DISCHARGE_THRESHOLD_KW
        except ValueError:
            return False

    def _get_export_watts(self) -> float:
        # site_power in kW; negative = exporting to grid (excess solar)
        state = self.hass.states.get(self._site_power_sensor)
        if state is None:
            _LOGGER.warning("Site power sensor %s unavailable", self._site_power_sensor)
            return 0.0
        try:
            kw = float(state.state)
            return max(0.0, -kw * 1000)
        except ValueError:
            return 0.0

    def _get_max_amps(self, evse_entity: str) -> int:
        state = self.hass.states.get(evse_entity)
        if state and "max_charging_rate" in state.attributes:
            return int(state.attributes["max_charging_rate"])
        return DEFAULT_MAX_AMPS

    async def _set_evse_current(self, evse_entity: str, amps: int) -> None:
        if self._last_targets.get(evse_entity) == amps:
            return

        previous = self._last_targets.get(evse_entity, "unset")
        _LOGGER.info("%s charging rate: %s A → %s A", evse_entity, previous, amps)
        self._last_targets[evse_entity] = amps

        if amps == 0:
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": evse_entity}, blocking=True
            )
        else:
            await self.hass.services.async_call(
                "emporia_vue",
                "set_charger_current",
                {"entity_id": evse_entity, "current": amps},
                blocking=True,
            )
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": evse_entity}, blocking=True
            )
