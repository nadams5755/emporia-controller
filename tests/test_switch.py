from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.emporia_controller.switch import _evse_friendly_name, EvseModeSwitch
from custom_components.emporia_controller.const import DOMAIN, ChargeMode

def make_state(value, attributes=None):
    state = MagicMock()
    state.state = str(value)
    state.attributes = attributes or {}
    return state

def make_switch(mode=ChargeMode.EXCESS_SOLAR, label="Excess Solar Charge", evse_name="My EVSE", current_mode=None):
    coordinator = MagicMock()
    coordinator.set_mode = AsyncMock()
    coordinator.get_mode = MagicMock(return_value=current_mode if current_mode is not None else mode)
    sw = EvseModeSwitch(coordinator, "switch.evse1", mode, label, evse_name)
    return sw

# ---------------------------------------------------------------------------
# _evse_friendly_name
# ---------------------------------------------------------------------------

def test_friendly_name_from_attribute():
    hass = MagicMock()
    hass.states.get.return_value = make_state("on", {"friendly_name": "Garage Charger"})
    assert _evse_friendly_name(hass, "switch.garage_charger") == "Garage Charger"

def test_friendly_name_fallback_strips_domain_and_title_cases():
    hass = MagicMock()
    hass.states.get.return_value = make_state("on", {})
    assert _evse_friendly_name(hass, "switch.my_garage_evse") == "My Garage Evse"

def test_friendly_name_fallback_when_state_unavailable():
    hass = MagicMock()
    hass.states.get.return_value = None
    assert _evse_friendly_name(hass, "switch.driveway_charger") == "Driveway Charger"

def test_friendly_name_strips_domain_prefix_correctly():
    hass = MagicMock()
    hass.states.get.return_value = None
    assert _evse_friendly_name(hass, "switch.evse") == "Evse"

# ---------------------------------------------------------------------------
# EvseModeSwitch — construction
# ---------------------------------------------------------------------------

def test_switch_name_is_evse_name_and_label():
    sw = make_switch(label="Excess Solar Charge", evse_name="My EVSE")
    assert sw._attr_name == "My EVSE - Excess Solar Charge"

def test_switch_unique_id_uses_domain_slug_and_mode():
    sw = make_switch(mode=ChargeMode.EXCESS_SOLAR)
    assert sw._attr_unique_id == f"{DOMAIN}_switch_evse1_excess_solar"

def test_switch_unique_id_replaces_dot_with_underscore():
    coordinator = MagicMock()
    coordinator.get_mode = MagicMock(return_value=ChargeMode.OVERRIDE)
    sw = EvseModeSwitch(coordinator, "switch.my.evse", ChargeMode.OVERRIDE, "lbl", "name")
    assert "." not in sw._attr_unique_id

@pytest.mark.parametrize(
    "mode, label",
    [
        (ChargeMode.EXCESS_SOLAR, "Excess Solar Charge"),
        (ChargeMode.FULL_SPEED_OFFPEAK, "Off-Peak Full Speed Charge"),
        (ChargeMode.OVERRIDE, "Full Speed Charge Now"),
    ],
)
def test_all_modes_produce_distinct_unique_ids(mode, label):
    coordinator = MagicMock()
    coordinator.get_mode = MagicMock(return_value=mode)
    sw = EvseModeSwitch(coordinator, "switch.evse1", mode, label, "EVSE")
    assert mode in sw._attr_unique_id

# ---------------------------------------------------------------------------
# EvseModeSwitch — is_on reflects coordinator mode
# ---------------------------------------------------------------------------

def test_is_on_when_mode_matches():
    sw = make_switch(mode=ChargeMode.OVERRIDE, current_mode=ChargeMode.OVERRIDE)
    assert sw.is_on is True

def test_is_off_when_mode_does_not_match():
    sw = make_switch(mode=ChargeMode.OVERRIDE, current_mode=ChargeMode.EXCESS_SOLAR)
    assert sw.is_on is False

@pytest.mark.parametrize("active_mode", [
    ChargeMode.EXCESS_SOLAR,
    ChargeMode.FULL_SPEED_OFFPEAK,
    ChargeMode.OVERRIDE,
])
def test_exactly_one_switch_is_on_for_each_mode(active_mode):
    switches = [
        make_switch(mode=mode, current_mode=active_mode)
        for mode, _ in [
            (ChargeMode.EXCESS_SOLAR, ""),
            (ChargeMode.FULL_SPEED_OFFPEAK, ""),
            (ChargeMode.OVERRIDE, ""),
        ]
    ]
    on_count = sum(1 for sw in switches if sw.is_on)
    assert on_count == 1

# ---------------------------------------------------------------------------
# EvseModeSwitch — async_turn_on / async_turn_off
# ---------------------------------------------------------------------------

async def test_turn_on_calls_set_mode():
    sw = make_switch(mode=ChargeMode.OVERRIDE)
    await sw.async_turn_on()
    sw.coordinator.set_mode.assert_called_once_with("switch.evse1", ChargeMode.OVERRIDE)

async def test_turn_on_excess_solar():
    sw = make_switch(mode=ChargeMode.EXCESS_SOLAR)
    await sw.async_turn_on()
    sw.coordinator.set_mode.assert_called_once_with("switch.evse1", ChargeMode.EXCESS_SOLAR)

async def test_turn_on_offpeak():
    sw = make_switch(mode=ChargeMode.FULL_SPEED_OFFPEAK)
    await sw.async_turn_on()
    sw.coordinator.set_mode.assert_called_once_with("switch.evse1", ChargeMode.FULL_SPEED_OFFPEAK)

async def test_turn_off_is_noop():
    sw = make_switch(mode=ChargeMode.OVERRIDE)
    await sw.async_turn_off()
    sw.coordinator.set_mode.assert_not_called()
