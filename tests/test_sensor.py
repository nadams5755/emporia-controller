from unittest.mock import MagicMock

from custom_components.emporia_controller.sensor import EvseStatusSensor
from custom_components.emporia_controller.const import DOMAIN, ChargeMode


def make_sensor(evse="switch.evse1", data=None, mode=ChargeMode.EXCESS_SOLAR, voltage=240):
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.get_mode = MagicMock(return_value=mode)
    coordinator.voltage = voltage
    return EvseStatusSensor(coordinator, evse, "Driveway")


# ---------------------------------------------------------------------------
# native_value
# ---------------------------------------------------------------------------

def test_native_value_charging_when_target_nonzero():
    s = make_sensor(data={"targets": {"switch.evse1": 12}, "skip_reasons": {}})
    assert s.native_value == "charging"

def test_native_value_idle_when_no_data():
    s = make_sensor(data=None)
    assert s.native_value == "idle"

def test_native_value_idle_when_evse_not_in_targets():
    s = make_sensor(data={"targets": {}, "skip_reasons": {}})
    assert s.native_value == "idle"

def test_native_value_idle_when_target_zero_and_mode_is_solar():
    s = make_sensor(
        data={"targets": {"switch.evse1": 0}, "skip_reasons": {"switch.evse1": "outside charging window"}},
        mode=ChargeMode.EXCESS_SOLAR,
    )
    assert s.native_value == "idle"

def test_native_value_idle_when_target_zero_and_mode_is_offpeak():
    s = make_sensor(
        data={"targets": {"switch.evse1": 0}, "skip_reasons": {"switch.evse1": "outside off-peak window"}},
        mode=ChargeMode.FULL_SPEED_OFFPEAK,
    )
    assert s.native_value == "idle"


# ---------------------------------------------------------------------------
# extra_state_attributes
# ---------------------------------------------------------------------------

def test_attributes_mode():
    s = make_sensor(
        data={"targets": {"switch.evse1": 8}, "skip_reasons": {},
              "export_watts": 2000.0, "available_watts": 2000.0, "powerwall_discharging": False},
        mode=ChargeMode.EXCESS_SOLAR,
    )
    assert s.extra_state_attributes["mode"] == ChargeMode.EXCESS_SOLAR

def test_attributes_target_amps():
    s = make_sensor(data={
        "targets": {"switch.evse1": 16}, "skip_reasons": {},
        "export_watts": 0.0, "available_watts": 0.0, "powerwall_discharging": False,
    })
    assert s.extra_state_attributes["target_amps"] == 16

def test_attributes_no_skip_reason_when_charging():
    s = make_sensor(data={
        "targets": {"switch.evse1": 8}, "skip_reasons": {},
        "export_watts": 2000.0, "available_watts": 2000.0, "powerwall_discharging": False,
    })
    assert "skip_reason" not in s.extra_state_attributes

def test_attributes_skip_reason_present_when_idle():
    s = make_sensor(data={
        "targets": {"switch.evse1": 0},
        "skip_reasons": {"switch.evse1": "outside charging window"},
        "export_watts": 0.0, "available_watts": 0.0, "powerwall_discharging": False,
    })
    assert s.extra_state_attributes["skip_reason"] == "outside charging window"

def test_attributes_export_and_available_watts():
    s = make_sensor(data={
        "targets": {"switch.evse1": 10}, "skip_reasons": {},
        "export_watts": 3000.0, "available_watts": 2400.0, "powerwall_discharging": False,
    })
    attrs = s.extra_state_attributes
    assert attrs["export_watts"] == 3000.0
    assert attrs["available_watts"] == 2400.0

def test_attributes_powerwall_discharging():
    s = make_sensor(data={
        "targets": {"switch.evse1": 0},
        "skip_reasons": {"switch.evse1": "powerwall discharging"},
        "export_watts": 1000.0, "available_watts": 0.0, "powerwall_discharging": True,
    })
    assert s.extra_state_attributes["powerwall_discharging"] is True

def test_attributes_target_kw_computed_from_amps_and_voltage():
    s = make_sensor(
        data={"targets": {"switch.evse1": 16}, "skip_reasons": {},
              "export_watts": 0.0, "available_watts": 0.0, "powerwall_discharging": False},
        voltage=240,
    )
    assert s.extra_state_attributes["target_kw"] == 3.84

def test_attributes_target_kw_none_when_target_zero():
    s = make_sensor(
        data={"targets": {"switch.evse1": 0}, "skip_reasons": {"switch.evse1": "outside charging window"},
              "export_watts": 0.0, "available_watts": 0.0, "powerwall_discharging": False},
        mode=ChargeMode.EXCESS_SOLAR,
    )
    assert s.extra_state_attributes["target_kw"] is None

def test_attributes_none_data_returns_nones():
    s = make_sensor(data=None)
    attrs = s.extra_state_attributes
    assert attrs["target_amps"] is None
    assert attrs["target_kw"] is None
    assert attrs["export_watts"] is None
    assert "skip_reason" not in attrs


# ---------------------------------------------------------------------------
# Entity identity
# ---------------------------------------------------------------------------

def test_unique_id_uses_slug_and_domain():
    s = make_sensor(evse="switch.evse1")
    assert s._attr_unique_id == f"{DOMAIN}_switch_evse1_status"

def test_unique_id_has_no_dots():
    s = make_sensor(evse="switch.my_evse")
    assert "." not in s._attr_unique_id

def test_name_includes_evse_name():
    s = make_sensor(evse="switch.evse1")
    assert "Driveway" in s._attr_name
    assert "Status" in s._attr_name
