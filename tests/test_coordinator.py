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
    c._last_targets["switch.evse1"] = 10  # simulate ongoing session
    # 2880 W / 240 V = 12 A; ramp cap: min(12, 10+2) = 12
    assert c._allocate_solar_current(["switch.evse1"], 2880.0, False) == {"switch.evse1": 12}

def test_allocate_floors_per_evse():
    c = make_coordinator()
    c._last_targets["switch.evse1"] = 11  # simulate ongoing session
    # 3100 W / 240 V = 12.9 → floor 12; ramp cap: min(12, 11+2) = 12
    assert c._allocate_solar_current(["switch.evse1"], 3100.0, False) == {"switch.evse1": 12}

def test_allocate_two_evses_split_evenly():
    c = make_coordinator(["switch.evse1", "switch.evse2"])
    c._last_targets["switch.evse1"] = 6
    c._last_targets["switch.evse2"] = 6
    # 2880 W / 240 V = 12 A; 12 // 2 = 6 A each; ramp cap: min(6, 6+2) = 6
    result = c._allocate_solar_current(["switch.evse1", "switch.evse2"], 2880.0, False)
    assert result == {"switch.evse1": 6, "switch.evse2": 6}

def test_allocate_below_minimum_single_evse():
    c = make_coordinator()
    # 1000 W / 240 V = 4 A < 6 A minimum, PW not discharging → stop
    assert c._allocate_solar_current(["switch.evse1"], 1000.0, False) == {"switch.evse1": 0}

def test_allocate_two_evses_split_below_minimum():
    c = make_coordinator(["switch.evse1", "switch.evse2"])
    # 2400 W / 240 V = 10 A; 10 // 2 = 5 A < 6 A, PW not discharging → 0 for all
    result = c._allocate_solar_current(["switch.evse1", "switch.evse2"], 2400.0, False)
    assert result == {"switch.evse1": 0, "switch.evse2": 0}

def test_allocate_exactly_at_minimum():
    c = make_coordinator()
    # 1440 W / 240 V = 6 A — exactly at minimum; last=0 → start at MIN
    assert c._allocate_solar_current(["switch.evse1"], 1440.0, False) == {"switch.evse1": 6}

def test_allocate_custom_voltage():
    c = make_coordinator(voltage=120)
    c._last_targets["switch.evse1"] = 10  # simulate ongoing session
    # 1440 W / 120 V = 12 A; ramp cap: min(12, 10+2) = 12
    assert c._allocate_solar_current(["switch.evse1"], 1440.0, False) == {"switch.evse1": 12}

def test_allocate_below_minimum_pw_discharging_floors_at_min():
    c = make_coordinator()
    c._last_targets["switch.evse1"] = 20
    # 500 W → 2 A < 6 A, but PW is discharging → floor at 6 A
    assert c._allocate_solar_current(["switch.evse1"], 500.0, True) == {"switch.evse1": 6}

def test_allocate_ramp_up_from_zero():
    c = make_coordinator()
    # last=0 (fresh start) → always begin at MIN_CHARGE_AMPS regardless of available
    assert c._allocate_solar_current(["switch.evse1"], 9600.0, False) == {"switch.evse1": 6}

def test_allocate_ramp_up_step():
    c = make_coordinator()
    c._last_targets["switch.evse1"] = 8
    # Available is 20 A but last was 8 → capped at 10 A (+2 step)
    assert c._allocate_solar_current(["switch.evse1"], 4800.0, False) == {"switch.evse1": 10}

def test_allocate_reduce_immediately():
    c = make_coordinator()
    c._last_targets["switch.evse1"] = 20
    # Available drops to 14 A → reduce immediately, no ramp limit on decreases
    assert c._allocate_solar_current(["switch.evse1"], 3360.0, False) == {"switch.evse1": 14}

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

async def test_set_evse_current_new_session_turns_on_before_set_rate():
    # emporia_vue ignores set_charger_current while the switch is off, so
    # we must turn on first and then set the rate.
    c = make_coordinator()
    await c._set_evse_current("switch.evse1", 16)
    calls = c.hass.services.async_call.call_args_list
    assert len(calls) == 2
    assert calls[0][0][:2] == ("switch", "turn_on")
    assert calls[1][0][:2] == ("emporia_vue", "set_charger_current")

async def test_set_evse_current_rate_change_turns_on_before_set_rate():
    c = make_coordinator()
    c._last_targets["switch.evse1"] = 12
    await c._set_evse_current("switch.evse1", 16)
    calls = c.hass.services.async_call.call_args_list
    assert len(calls) == 2
    assert calls[0][0][:2] == ("switch", "turn_on")
    assert calls[1][0][:2] == ("emporia_vue", "set_charger_current")

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
    c._last_targets["switch.evse1"] = 6  # simulate already-charging session
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

async def test_control_loop_excess_solar_deducts_battery_discharge_from_budget():
    # export 3000W, battery discharging 1000W → available = 2000W → 8A (not 12A)
    c = make_loop_coordinator(
        export_kw=-3.0,
        battery_kw=1.0,
        modes={"switch.evse1": ChargeMode.EXCESS_SOLAR},
    )
    c._last_targets["switch.evse1"] = 6  # simulate already-charging session
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 8

async def test_control_loop_excess_solar_stops_when_battery_drain_exceeds_solar():
    # export 2000W, battery discharging 1000W → available = 1000W → 4A < min → 0
    c = make_loop_coordinator(
        export_kw=-2.0,
        battery_kw=1.0,
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
    evses = ["switch.evse1", "switch.evse2"]
    c = make_loop_coordinator(
        export_kw=-2.0,
        battery_kw=0.0,
        evse_entities=evses,
        modes={
            "switch.evse1": ChargeMode.OVERRIDE,
            "switch.evse2": ChargeMode.EXCESS_SOLAR,
        },
    )
    c._last_targets["switch.evse2"] = 6  # simulate already-charging session
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["targets"]["switch.evse1"] == 48
    assert result["targets"]["switch.evse2"] == 8  # 2000 W / 240 V = 8 A (sole solar EVSE)

async def test_control_loop_returns_powerwall_and_export_state():
    c = make_loop_coordinator(export_kw=-1.0, battery_kw=0.5)
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["powerwall_discharging"] is True
    assert result["export_watts"] == pytest.approx(1000.0)
    assert "skip_reasons" in result
    assert "available_watts" in result


async def test_control_loop_skip_reason_offpeak_outside_window():
    c = make_loop_coordinator(battery_kw=0.0, modes={"switch.evse1": ChargeMode.FULL_SPEED_OFFPEAK})
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(20)
        result = await c._run_control_loop()
    assert result["skip_reasons"]["switch.evse1"] == "outside off-peak window"


async def test_control_loop_skip_reason_solar_outside_window():
    c = make_loop_coordinator(battery_kw=0.0, modes={"switch.evse1": ChargeMode.EXCESS_SOLAR})
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(20)
        result = await c._run_control_loop()
    assert result["skip_reasons"]["switch.evse1"] == "outside charging window"


async def test_control_loop_skip_reason_insufficient_solar():
    c = make_loop_coordinator(
        export_kw=-1.0,  # 1000 W / 240 V = 4 A < 6 A minimum
        battery_kw=0.0,
        modes={"switch.evse1": ChargeMode.EXCESS_SOLAR},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert "insufficient solar" in result["skip_reasons"]["switch.evse1"]


async def test_control_loop_no_skip_reason_for_charging_override():
    c = make_loop_coordinator(modes={"switch.evse1": ChargeMode.OVERRIDE})
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert "switch.evse1" not in result["skip_reasons"]


async def test_control_loop_available_watts_set_for_solar_evses():
    c = make_loop_coordinator(
        export_kw=-2.0,
        battery_kw=0.0,
        modes={"switch.evse1": ChargeMode.EXCESS_SOLAR},
    )
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["available_watts"] == pytest.approx(2000.0)


async def test_control_loop_available_watts_zero_when_no_solar_evses():
    c = make_loop_coordinator(modes={"switch.evse1": ChargeMode.OVERRIDE})
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(10)
        result = await c._run_control_loop()
    assert result["available_watts"] == 0.0

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
    c._store.async_load.return_value = {"evse_modes": {"switch.evse1": ChargeMode.OVERRIDE}}
    await c.async_load_state()
    assert c._evse_modes["switch.evse1"] == ChargeMode.OVERRIDE

async def test_load_state_normalizes_retired_mode_to_default():
    c = make_coordinator(["switch.evse1"])
    c._store.async_load.return_value = {"evse_modes": {"switch.evse1": "stopped"}}
    await c.async_load_state()
    assert c._evse_modes["switch.evse1"] == ChargeMode.EXCESS_SOLAR

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
    c._evse_modes["switch.evse1"] = ChargeMode.OVERRIDE
    assert c.get_mode("switch.evse1") == ChargeMode.OVERRIDE

async def test_set_mode_updates_evse_mode():
    c = make_coordinator()
    c._evse_modes["switch.evse1"] = ChargeMode.EXCESS_SOLAR
    await c.set_mode("switch.evse1", ChargeMode.OVERRIDE)
    assert c._evse_modes["switch.evse1"] == ChargeMode.OVERRIDE

async def test_set_mode_persists_state():
    c = make_coordinator()
    await c.set_mode("switch.evse1", ChargeMode.OVERRIDE)
    c._store.async_save.assert_called_once_with(
        {"evse_modes": c._evse_modes}
    )
