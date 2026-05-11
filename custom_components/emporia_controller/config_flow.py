from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_POWER_SENSOR,
    CONF_DEBUG_LOGGING,
    CONF_DISABLED,
    CONF_EVSE_ENTITIES,
    CONF_RESET_STATE,
    CONF_SITE_POWER_SENSOR,
    CONF_VOLTAGE,
    DEFAULT_VOLTAGE,
    DOMAIN,
)

def _build_schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_EVSE_ENTITIES,
                default=defaults.get(CONF_EVSE_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch", multiple=True)
            ),
            vol.Required(
                CONF_SITE_POWER_SENSOR,
                default=defaults.get(CONF_SITE_POWER_SENSOR, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_BATTERY_POWER_SENSOR,
                default=defaults.get(CONF_BATTERY_POWER_SENSOR, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_VOLTAGE,
                default=defaults.get(CONF_VOLTAGE, DEFAULT_VOLTAGE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=100, max=480, step=1, unit_of_measurement="V", mode="box"
                )
            ),
            vol.Optional(
                CONF_DEBUG_LOGGING,
                default=defaults.get(CONF_DEBUG_LOGGING, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_DISABLED,
                default=defaults.get(CONF_DISABLED, False),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_RESET_STATE,
                default=defaults.get(CONF_RESET_STATE, False),
            ): selector.BooleanSelector(),
        }
    )

class EmporiaControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Emporia EVSE Controller", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema({}),
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return EmporiaControllerOptionsFlow(config_entry)

class EmporiaControllerOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(current),
        )
