import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.emporia_controller.button import _evse_friendly_name, EvseModeButton
from custom_components.emporia_controller.const import DOMAIN, ChargeMode


def make_state(value, attributes=None):
    state = MagicMock()
    state.state = str(value)
    state.attributes = attributes or {}
    return state


def make_button(mode=ChargeMode.STOPPED, label="Stop Charging", evse_name="My EVSE"):
    coordinator = MagicMock()
    coordinator.set_mode = AsyncMock()
    return EvseModeButton(coordinator, "switch.evse1", mode, label, evse_name)


# ---------------------------------------------------------------------------
# _evse_friendly_name
# ---------------------------------------------------------------------------


def test_friendly_name_from_attribute():
    hass = MagicMock()
    hass.states.get.return_value = make_state("on", {"friendly_name": "Garage Charger"})
    assert _evse_friendly_name(hass, "switch.garage_charger") == "Garage Charger"


def test_friendly_name_fallback_strips_domain_and_title_cases():
    hass = MagicMock()
    hass.states.get.return_value = make_state("on", {})  # no friendly_name
    assert _evse_friendly_name(hass, "switch.my_garage_evse") == "My Garage Evse"


def test_friendly_name_fallback_when_state_unavailable():
    hass = MagicMock()
    hass.states.get.return_value = None
    assert _evse_friendly_name(hass, "switch.driveway_charger") == "Driveway Charger"


def test_friendly_name_strips_domain_prefix_correctly():
    hass = MagicMock()
    hass.states.get.return_value = None
    # Entity ID with dots in the object_id part shouldn't happen, but domain strip is safe
    assert _evse_friendly_name(hass, "switch.evse") == "Evse"


# ---------------------------------------------------------------------------
# EvseModeButton — construction
# ---------------------------------------------------------------------------


def test_button_name_is_evse_name_and_label():
    btn = make_button(label="Stop Charging", evse_name="My EVSE")
    assert btn._attr_name == "My EVSE - Stop Charging"


def test_button_unique_id_uses_domain_slug_and_mode():
    btn = make_button(mode=ChargeMode.STOPPED)
    assert btn._attr_unique_id == f"{DOMAIN}_switch_evse1_stopped"


def test_button_unique_id_replaces_dot_with_underscore():
    coordinator = MagicMock()
    btn = EvseModeButton(coordinator, "switch.my.evse", ChargeMode.OVERRIDE, "lbl", "name")
    assert "." not in btn._attr_unique_id


@pytest.mark.parametrize(
    "mode, label",
    [
        (ChargeMode.EXCESS_SOLAR, "Charge on Excess Solar"),
        (ChargeMode.FULL_SPEED_OFFPEAK, "Charge Full Speed Off-Peak"),
        (ChargeMode.OVERRIDE, "Charge Full Speed Now"),
        (ChargeMode.STOPPED, "Stop Charging"),
    ],
)
def test_all_four_modes_produce_distinct_unique_ids(mode, label):
    coordinator = MagicMock()
    btn = EvseModeButton(coordinator, "switch.evse1", mode, label, "EVSE")
    assert mode in btn._attr_unique_id


# ---------------------------------------------------------------------------
# EvseModeButton — async_press
# ---------------------------------------------------------------------------


async def test_press_calls_set_mode_with_correct_args():
    btn = make_button(mode=ChargeMode.OVERRIDE)
    await btn.async_press()
    btn._coordinator.set_mode.assert_called_once_with("switch.evse1", ChargeMode.OVERRIDE)


async def test_press_excess_solar_button():
    btn = make_button(mode=ChargeMode.EXCESS_SOLAR)
    await btn.async_press()
    btn._coordinator.set_mode.assert_called_once_with("switch.evse1", ChargeMode.EXCESS_SOLAR)


async def test_press_stopped_button():
    btn = make_button(mode=ChargeMode.STOPPED)
    await btn.async_press()
    btn._coordinator.set_mode.assert_called_once_with("switch.evse1", ChargeMode.STOPPED)
