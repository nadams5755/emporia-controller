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
    CONF_DEBUG_LOGGING,
    CONF_DISABLED,
    CONF_EVSE_ENTITIES,
    CONF_RESET_STATE,
    CONF_SITE_POWER_SENSOR,
    CONF_VOLTAGE,
    DEFAULT_MAX_AMPS,
    DEFAULT_VOLTAGE,
    DOMAIN,
    MIN_CHARGE_AMPS,
    OFFPEAK_END_HOUR,
    SOLAR_RATE_STEP_AMPS,
    STORAGE_KEY,
    STORAGE_VERSION,
    UPDATE_INTERVAL_SECONDS,
    ChargeMode,
)

_LOGGER = logging.getLogger(__name__)


def _solar_skip_reason(in_charging_window: bool) -> str:
    if not in_charging_window:
        return "outside charging window"
    return "no vehicle connected"

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
        self._disabled: bool = config.get(CONF_DISABLED, False)
        self._last_targets: dict[str, int] = {}
        _LOGGER.setLevel(
            logging.DEBUG if config.get(CONF_DEBUG_LOGGING, False) else logging.NOTSET
        )

    async def async_load_state(self) -> None:
        config = {**self._entry.data, **self._entry.options}
        if config.get(CONF_RESET_STATE, False):
            _LOGGER.info("Resetting persisted state as requested by configuration")
            await self._store.async_remove()
            self.hass.config_entries.async_update_entry(
                self._entry,
                options={**self._entry.options, CONF_RESET_STATE: False},
            )
        else:
            data = await self._store.async_load()
            if data:
                self._evse_modes = data.get("evse_modes", {})
        for evse in self._evse_entities:
            self._evse_modes.setdefault(evse, ChargeMode.EXCESS_SOLAR)

    async def _save_state(self) -> None:
        await self._store.async_save({"evse_modes": self._evse_modes})

    @property
    def voltage(self) -> int:
        return self._voltage

    def get_mode(self, evse_entity: str) -> str:
        return self._evse_modes.get(evse_entity, ChargeMode.EXCESS_SOLAR)

    async def set_mode(self, evse_entity: str, mode: str) -> None:
        old_mode = self._evse_modes.get(evse_entity, ChargeMode.EXCESS_SOLAR)
        self._evse_modes[evse_entity] = mode
        _LOGGER.info("%s mode changed: %s → %s", evse_entity, old_mode, mode)
        await self._save_state()
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict:
        if self._disabled:
            _LOGGER.debug("Controller disabled — skipping control loop")
            return {}
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

        _LOGGER.debug(
            "Control loop: hour=%d window=%s offpeak=%s pw_discharging=%s export=%.0fW",
            hour, in_charging_window, in_offpeak, powerwall_discharging, export_watts,
        )

        targets: dict[str, int] = {}
        skip_reasons: dict[str, str] = {}
        solar_evses: list[str] = []
        available_watts: float = 0.0

        for evse in self._evse_entities:
            mode = self._evse_modes.get(evse, ChargeMode.EXCESS_SOLAR)

            if mode == ChargeMode.STOPPED:
                targets[evse] = 0
                skip_reasons[evse] = "stopped"

            elif mode == ChargeMode.OVERRIDE:
                targets[evse] = self._get_max_amps(evse)

            elif mode == ChargeMode.FULL_SPEED_OFFPEAK:
                if in_offpeak and not powerwall_discharging:
                    targets[evse] = self._get_max_amps(evse)
                else:
                    reason = "powerwall discharging" if powerwall_discharging else "outside off-peak window"
                    _LOGGER.debug("%s full_speed_offpeak skipped: %s", evse, reason)
                    targets[evse] = 0
                    skip_reasons[evse] = reason

            elif mode == ChargeMode.EXCESS_SOLAR:
                if in_charging_window and self._has_vehicle_connected(evse):
                    solar_evses.append(evse)
                else:
                    reason = _solar_skip_reason(in_charging_window)
                    _LOGGER.debug("%s excess_solar skipped: %s", evse, reason)
                    targets[evse] = 0
                    skip_reasons[evse] = reason

        if solar_evses:
            available_watts = self._get_available_solar_watts(solar_evses)
            targets.update(self._allocate_solar_current(solar_evses, available_watts, powerwall_discharging))
            if not any(targets.get(e, 0) > 0 for e in solar_evses):
                skip_reasons.update(dict.fromkeys(
                    solar_evses, f"insufficient solar ({available_watts:.0f} W available)"
                ))

        for evse, amps in targets.items():
            await self._set_evse_current(evse, amps)

        return {
            "targets": targets,
            "skip_reasons": skip_reasons,
            "powerwall_discharging": powerwall_discharging,
            "export_watts": export_watts,
            "available_watts": available_watts,
        }

    def _allocate_solar_current(
        self, evses: list[str], export_watts: float, powerwall_discharging: bool
    ) -> dict[str, int]:
        available_amps = int(export_watts / self._voltage)
        per_evse = available_amps // len(evses)

        if per_evse < MIN_CHARGE_AMPS:
            any_was_charging = any(self._last_targets.get(e, 0) > 0 for e in evses)
            if powerwall_discharging and any_was_charging:
                # Charger was already running and PW compensated for marginal solar.
                # Floor at minimum rather than stopping to avoid the off/on oscillation cycle.
                _LOGGER.debug(
                    "Solar allocation: %dA each — below minimum while PW discharging,"
                    " flooring at %dA",
                    per_evse, MIN_CHARGE_AMPS,
                )
                return {evse: MIN_CHARGE_AMPS for evse in evses}
            _LOGGER.debug(
                "Solar allocation: %.0fW / %dV / %d EVSE = %dA each — below %dA minimum, stopping all",
                export_watts, self._voltage, len(evses), per_evse, MIN_CHARGE_AMPS,
            )
            return {evse: 0 for evse in evses}

        # Ramp up gradually to avoid immediately overshooting available solar.
        # Reductions are applied immediately; increases are capped at SOLAR_RATE_STEP_AMPS/cycle.
        results = {}
        for evse in evses:
            last = self._last_targets.get(evse, 0)
            if last == 0:
                results[evse] = MIN_CHARGE_AMPS  # start at minimum when initiating a session
            elif per_evse < last:
                results[evse] = per_evse  # reduce immediately
            else:
                results[evse] = min(per_evse, last + SOLAR_RATE_STEP_AMPS)  # increase gradually
        return results

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

    def _get_battery_discharge_watts(self) -> float:
        state = self.hass.states.get(self._battery_power_sensor)
        if state is None:
            return 0.0
        try:
            return max(0.0, float(state.state) * 1000)
        except ValueError:
            return 0.0

    def _get_battery_charge_watts(self) -> float:
        # battery_power in kW; negative = charging from solar/grid
        state = self.hass.states.get(self._battery_power_sensor)
        if state is None:
            return 0.0
        try:
            return max(0.0, -float(state.state) * 1000)
        except ValueError:
            return 0.0

    def _get_available_solar_watts(self, solar_evses: list[str]) -> float:
        # Solar budget = current site export + what our solar-mode EVSEs are already consuming
        # - battery discharge (not solar-sourced) - battery charge (solar already spoken for).
        # Without reclaim, the site sensor drops to ~0 the moment charging starts, which would
        # cause the controller to immediately turn the charger back off.
        state = self.hass.states.get(self._site_power_sensor)
        if state is None:
            _LOGGER.warning("Site power sensor %s unavailable", self._site_power_sensor)
            return 0.0
        try:
            raw_export = -float(state.state) * 1000  # negative site_kw → positive export
            reclaim = sum(
                self._last_targets.get(evse, 0) * self._voltage for evse in solar_evses
            )
            battery_discharge = self._get_battery_discharge_watts()
            battery_charge = self._get_battery_charge_watts()
            available = max(0.0, raw_export + reclaim - battery_discharge - battery_charge)
            _LOGGER.debug(
                "Solar budget: site_export=%.0fW reclaim=%.0fW battery_discharge=%.0fW"
                " battery_charge=%.0fW available=%.0fW",
                raw_export, reclaim, battery_discharge, battery_charge, available,
            )
            return available
        except ValueError:
            return 0.0

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
        previous = self._last_targets.get(evse_entity)
        if previous == amps:
            return

        _LOGGER.info(
            "%s charging rate: %s A → %s A",
            evse_entity, previous if previous is not None else "unset", amps,
        )
        self._last_targets[evse_entity] = amps

        if amps == 0:
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": evse_entity}, blocking=True
            )
        elif not previous:  # new session — configure rate before enabling
            await self.hass.services.async_call(
                "emporia_vue",
                "set_charger_current",
                {"entity_id": evse_entity, "current": amps},
                blocking=True,
            )
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": evse_entity}, blocking=True
            )
        else:  # rate change while already charging
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": evse_entity}, blocking=True
            )
            await self.hass.services.async_call(
                "emporia_vue",
                "set_charger_current",
                {"entity_id": evse_entity, "current": amps},
                blocking=True,
            )
