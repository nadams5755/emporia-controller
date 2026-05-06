from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.emporia_controller.coordinator import EmporiaCoordinator
from custom_components.emporia_controller.const import (
    BATTERY_DISCHARGE_THRESHOLD_KW,
    CONF_BATTERY_POWER_SENSOR,
    CONF_EVSE_ENTITIES,
    CONF_SITE_POWER_SENSOR,
    CONF_VOLTAGE,
    DEFAULT_MAX_AMPS,
    DEFAULT_VOLTAGE,
    ChargeMode,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_state(value, attributes=None):
    state = MagicMock()
    state.state = str(value)
    state.attributes = attributes or {}
    return state

def make_coordinator(evse_entities=None, voltage=DEFAULT_VOLTAGE):
    """Return an EmporiaCoordinator backed by mock HA objects."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=None)

    entry = MagicMock()
    entry.data = {
        CONF_EVSE_ENTITIES: evse_entities or ["switch.evse1"],
        CONF_SITE_POWER_SENSOR: "sensor.site_power",
        CONF_BATTERY_POWER_SENSOR: "sensor.battery",
        CONF_VOLTAGE: voltage,
    }
    entry.options = {}

    coordinator = EmporiaCoordinator(hass, entry)

    # Replace the real Store with a fully controllable async mock.
    store = AsyncMock()
    store.async_load = AsyncMock(return_value=None)
    store.async_save = AsyncMock()
    coordinator._store = store

    return coordinator

def make_loop_coordinator(
    export_kw=-2.0,
    battery_kw=0.0,
    evse_entities=None,
    modes=None,
):
    """Return a coordinator pre-wired with sensor states for control-loop tests."""
    entities = evse_entities or ["switch.evse1"]
    coordinator = make_coordinator(evse_entities=entities)
    coordinator._evse_modes = modes or {e: ChargeMode.EXCESS_SOLAR for e in entities}

    def get_state(entity_id):
        if entity_id == "sensor.site_power":
            return make_state(str(export_kw))
        if entity_id == "sensor.battery":
            return make_state(str(battery_kw))
        return make_state("on", {"max_charging_rate": 48})

    coordinator.hass.states.get = MagicMock(side_effect=get_state)
    return coordinator

def at(hour):
    return datetime(2024, 1, 1, hour, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# _allocate_solar_current
# ---------------------------------------------------------------------------

def test_allocate_single_evse_enough_power():
    c = make_coordinator()
    # 2880 W / 240 V = 12 A
    assert c._allocate_solar_current(["switch.evse1"], 2880.0) == {"switch.evse1": 12}

def test_allocate_floors_per_evse():
    c = make_coordinator()
    # 3000 W / 240 V = 12 A; 12 // 1 = 12 (no rounding issue here)
    # Use non-divisible wattage: 3100 W / 240 V = 12.9 → floor 12
    assert c._allocate_solar_current(["switch.evse1"], 3100.0) == {"switch.evse1": 12}

def test_allocate_two_evses_split_evenly():
    c = make_coordinator(["switch.evse1", "switch.evse2"])
    # 2880 W / 240 V = 12 A; 12 // 2 = 6 A each
    result = c._allocate_solar_current(["switch.evse1", "switch.evse2"], 2880.0)
    assert result == {"switch.evse1": 6, "switch.evse2": 6}

def test_allocate_below_minimum_single_evse():
    c = make_coordinator()
    # 1000 W / 240 V = 4 A < 6 A minimum → 0
    assert c._allocate_solar_current(["switch.evse1"], 1000.0) == {"switch.evse1": 0}

def test_allocate_two_evses_split_below_minimum():
    c = make_coordinator(["switch.evse1", "switch.evse2"])
    # 2400 W / 240 V = 10 A; 10 // 2 = 5 A < 6 A → 0 for all
    result = c._allocate_solar_current(["switch.evse1", "switch.evse2"], 2400.0)
    assert result == {"switch.evse1": 0, "switch.evse2": 0}

def test_allocate_exactly_at_minimum():
    c = make_coordinator()
    # 1440 W / 240 V = 6 A — exactly at minimum, should charge
    assert c._allocate_solar_current(["switch.evse1"], 1440.0) == {"switch.evse1": 6}

def test_allocate_custom_voltage():
    c = make_coordinator(voltage=120)
    # 1440 W / 120 V = 12 A
    assert c._allocate_solar_current(["switch.evse1"], 1440.0) == {"switch.evse1": 12}

# ---------------------------------------------------------------------------
# _is_powerwall_discharging
# ---------------------------------------------------------------------------

def test_powerwall_discharging_above_threshold():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("1.0")
    assert c._is_powerwall_discharging() is True

def test_powerwall_not_discharging_zero():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("0.0")
    assert c._is_powerwall_discharging() is False

def test_powerwall_not_discharging_below_threshold():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("0.05")
    assert c._is_powerwall_discharging() is False

def test_powerwall_at_threshold_is_not_discharging():
    c = make_coordinator()
    # Threshold check is > 0.1, so exactly 0.1 is False
    c.hass.states.get.return_value = make_state(str(BATTERY_DISCHARGE_THRESHOLD_KW))
    assert c._is_powerwall_discharging() is False

def test_powerwall_charging_negative():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("-2.0")
    assert c._is_powerwall_discharging() is False

def test_powerwall_sensor_unavailable():
    c = make_coordinator()
    c.hass.states.get.return_value = None
    assert c._is_powerwall_discharging() is False

def test_powerwall_sensor_non_numeric():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("unavailable")
    assert c._is_powerwall_discharging() is False

# ---------------------------------------------------------------------------
# _get_export_watts
# ---------------------------------------------------------------------------

def test_export_watts_exporting():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("-2.0")  # -2 kW = 2000 W export
    assert c._get_export_watts() == pytest.approx(2000.0)

def test_export_watts_importing():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("1.5")  # positive = importing
    assert c._get_export_watts() == 0.0

def test_export_watts_balanced():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("0.0")
    assert c._get_export_watts() == 0.0

def test_export_watts_sensor_unavailable():
    c = make_coordinator()
    c.hass.states.get.return_value = None
    assert c._get_export_watts() == 0.0

def test_export_watts_sensor_non_numeric():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("unavailable")
    assert c._get_export_watts() == 0.0

# ---------------------------------------------------------------------------
# _get_max_amps
# ---------------------------------------------------------------------------

def test_get_max_amps_with_attribute():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("on", {"max_charging_rate": 32})
    assert c._get_max_amps("switch.evse1") == 32

def test_get_max_amps_no_attribute_falls_back_to_default():
    c = make_coordinator()
    c.hass.states.get.return_value = make_state("on", {})
    assert c._get_max_amps("switch.evse1") == DEFAULT_MAX_AMPS

def test_get_max_amps_no_state_falls_back_to_default():
    c = make_coordinator()
    c.hass.states.get.return_value = None
    assert c._get_max_amps("switch.evse1") == DEFAULT_MAX_AMPS

# ---------------------------------------------------------------------------
# _set_evse_current
# ---------------------------------------------------------------------------

async def test_set_evse_current_zero_calls_turn_off():
    c = make_coordinator()
    await c._set_evse_current("switch.evse1", 0)
    c.hass.services.async_call.assert_called_once_with(
        "switch", "turn_off", {"entity_id": "switch.evse1"}, blocking=True
    )

async def test_set_evse_current_nonzero_sets_rate_then_turns_on():
    c = make_coordinator()
    await c._set_evse_current("switch.evse1", 16)
    assert c.hass.services.async_call.call_count == 2
    c.hass.services.async_call.assert_any_call(
        "emporia_vue",
        "set_charger_current",
        {"entity_id": "switch.evse1", "current": 16},
        blocking=True,
    )
    c.hass.services.async_call.assert_any_call(
        "switch", "turn_on", {"entity_id": "switch.evse1"}, blocking=True
    )

async def test_set_evse_current_deduplication_skips_call():
    c = make_coordinator()
    c._last_targets["switch.evse1"] = 12
    await c._set_evse_current("switch.evse1", 12)
    c.hass.services.async_call.assert_not_called()

async def test_set_evse_current_updates_last_targets():
    c = make_coordinator()
    await c._set_evse_current("switch.evse1", 20)
    assert c._last_targets["switch.evse1"] == 20

async def test_set_evse_current_change_from_previous_calls_service():
    c = make_coordinator()
    c._last_targets["switch.evse1"] = 12
    await c._set_evse_current("switch.evse1", 16)  # changed → must call
    c.hass.services.async_call.assert_called()

# ---------------------------------------------------------------------------
# _run_control_loop — mode logic
# ---------------------------------------------------------------------------

async def test_control_loop_stopped_mode():
    c = make_loop_coordinator(modes={"switch.evse1": ChargeMode.STOPPED})
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 0

async def test_control_loop_override_ignores_time_and_powerwall():
    c = make_loop_coordinator(
        battery_kw=2.0,  # powerwall discharging
        modes={"switch.evse1": ChargeMode.OVERRIDE},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(20)  # outside charging window
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 48

async def test_control_loop_offpeak_in_window_not_discharging():
    c = make_loop_coordinator(
        battery_kw=0.0,
        modes={"switch.evse1": ChargeMode.FULL_SPEED_OFFPEAK},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)  # 10am — in off-peak window
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 48

async def test_control_loop_offpeak_at_window_boundary():
    c = make_loop_coordinator(
        battery_kw=0.0,
        modes={"switch.evse1": ChargeMode.FULL_SPEED_OFFPEAK},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(15)  # 3pm = OFFPEAK_END_HOUR, exclusive → stops
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 0

async def test_control_loop_offpeak_powerwall_discharging():
    c = make_loop_coordinator(
        battery_kw=1.0,  # discharging
        modes={"switch.evse1": ChargeMode.FULL_SPEED_OFFPEAK},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 0

async def test_control_loop_excess_solar_charges_when_exporting():
    c = make_loop_coordinator(
        export_kw=-2.0,  # 2000 W export → 2000/240 = 8 A
        battery_kw=0.0,
        modes={"switch.evse1": ChargeMode.EXCESS_SOLAR},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 8

async def test_control_loop_excess_solar_stops_outside_charging_window():
    c = make_loop_coordinator(
        export_kw=-2.0,
        battery_kw=0.0,
        modes={"switch.evse1": ChargeMode.EXCESS_SOLAR},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(16)  # 4pm = CHARGING_WINDOW_END_HOUR, exclusive
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 0

async def test_control_loop_excess_solar_stops_when_powerwall_discharging():
    c = make_loop_coordinator(
        export_kw=-2.0,
        battery_kw=1.0,  # discharging
        modes={"switch.evse1": ChargeMode.EXCESS_SOLAR},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 0

async def test_control_loop_excess_solar_stops_when_not_exporting():
    c = make_loop_coordinator(
        export_kw=1.5,  # importing
        battery_kw=0.0,
        modes={"switch.evse1": ChargeMode.EXCESS_SOLAR},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 0

async def test_control_loop_two_solar_evses_split_current():
    evses = ["switch.evse1", "switch.evse2"]
    c = make_loop_coordinator(
        export_kw=-2.88,  # 2880 W / 240 V = 12 A → 6 A each
        battery_kw=0.0,
        evse_entities=evses,
        modes={e: ChargeMode.EXCESS_SOLAR for e in evses},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 6
    assert result["targets"]["switch.evse2"] == 6

async def test_control_loop_mixed_modes():
    evses = ["switch.evse1", "switch.evse2", "switch.evse3"]
    c = make_loop_coordinator(
        export_kw=-2.0,
        battery_kw=0.0,
        evse_entities=evses,
        modes={
            "switch.evse1": ChargeMode.STOPPED,
            "switch.evse2": ChargeMode.OVERRIDE,
            "switch.evse3": ChargeMode.EXCESS_SOLAR,
        },
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 0
    assert result["targets"]["switch.evse2"] == 48
    assert result["targets"]["switch.evse3"] == 8  # 2000 W / 240 V = 8 A (sole solar EVSE)

async def test_control_loop_returns_powerwall_and_export_state():
    c = make_loop_coordinator(export_kw=-1.0, battery_kw=0.5)
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["powerwall_discharging"] is True
    assert result["export_watts"] == pytest.approx(1000.0)

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

async def test_load_state_defaults_to_excess_solar_when_no_data():
    c = make_coordinator(["switch.evse1", "switch.evse2"])
    c._store.async_load.return_value = None
    await c.async_load_state()
    assert c._evse_modes["switch.evse1"] == ChargeMode.EXCESS_SOLAR
    assert c._evse_modes["switch.evse2"] == ChargeMode.EXCESS_SOLAR

async def test_load_state_restores_persisted_modes():
    c = make_coordinator(["switch.evse1"])
    c._store.async_load.return_value = {"evse_modes": {"switch.evse1": ChargeMode.STOPPED}}
    await c.async_load_state()
    assert c._evse_modes["switch.evse1"] == ChargeMode.STOPPED

async def test_load_state_defaults_missing_evses():
    c = make_coordinator(["switch.evse1", "switch.evse2"])
    c._store.async_load.return_value = {"evse_modes": {"switch.evse1": ChargeMode.OVERRIDE}}
    await c.async_load_state()
    assert c._evse_modes["switch.evse1"] == ChargeMode.OVERRIDE
    assert c._evse_modes["switch.evse2"] == ChargeMode.EXCESS_SOLAR

def test_get_mode_defaults_unknown_evse():
    c = make_coordinator()
    assert c.get_mode("switch.unknown") == ChargeMode.EXCESS_SOLAR

def test_get_mode_returns_stored_mode():
    c = make_coordinator()
    c._evse_modes["switch.evse1"] = ChargeMode.STOPPED
    assert c.get_mode("switch.evse1") == ChargeMode.STOPPED

async def test_set_mode_updates_evse_mode():
    c = make_coordinator()
    c._evse_modes["switch.evse1"] = ChargeMode.EXCESS_SOLAR
    await c.set_mode("switch.evse1", ChargeMode.OVERRIDE)
    assert c._evse_modes["switch.evse1"] == ChargeMode.OVERRIDE

async def test_set_mode_persists_state():
    c = make_coordinator()
    await c.set_mode("switch.evse1", ChargeMode.STOPPED)
    c._store.async_save.assert_called_once_with(
        {"evse_modes": c._evse_modes}
    )
