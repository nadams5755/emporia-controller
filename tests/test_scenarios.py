"""
End-user behavior scenarios.

Each test describes a real situation a user might encounter and asserts
what the controller does automatically, without them pressing anything.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.emporia_controller.coordinator import EmporiaCoordinator
from custom_components.emporia_controller.const import (
    CONF_BATTERY_POWER_SENSOR,
    CONF_EVSE_ENTITIES,
    CONF_SITE_POWER_SENSOR,
    CONF_VOLTAGE,
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

def make_coordinator(evse_entities, voltage=DEFAULT_VOLTAGE):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()

    entry = MagicMock()
    entry.data = {
        CONF_EVSE_ENTITIES: evse_entities,
        CONF_SITE_POWER_SENSOR: "sensor.site_power",
        CONF_BATTERY_POWER_SENSOR: "sensor.battery",
        CONF_VOLTAGE: voltage,
    }
    entry.options = {}

    coordinator = EmporiaCoordinator(hass, entry)

    store = AsyncMock()
    store.async_load = AsyncMock(return_value=None)
    store.async_save = AsyncMock()
    coordinator._store = store

    return coordinator

def scenario(evse_entities, modes, export_kw, battery_kw, voltage=DEFAULT_VOLTAGE):
    """Build a coordinator and wire up sensor states for a scenario test."""
    coordinator = make_coordinator(evse_entities, voltage=voltage)
    coordinator._evse_modes = modes

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

async def run_loop(coordinator, hour):
    with patch("custom_components.emporia_controller.coordinator.dt_util") as dt:
        dt.now.return_value = at(hour)
        return await coordinator._run_control_loop()

# ---------------------------------------------------------------------------
# Default mode (excess solar) — no user action required
# ---------------------------------------------------------------------------

async def test_plug_in_at_midnight_no_solar_does_not_charge():
    """After midnight there's no sun, so an EV plugged in on the default mode waits."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.EXCESS_SOLAR},
        export_kw=0.5,   # home is importing, not exporting
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=0)
    assert result["targets"]["switch.driveway"] == 0

async def test_plug_in_at_1pm_sunny_day_charges_on_solar():
    """On a sunny afternoon with excess solar the car charges automatically."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.EXCESS_SOLAR},
        export_kw=-3.0,   # 3000 W export → 3000/240 = 12 A
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=13)
    assert result["targets"]["switch.driveway"] == 12

async def test_plug_in_at_1pm_cloudy_day_does_not_charge():
    """On a cloudy afternoon with no excess solar the car just sits."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.EXCESS_SOLAR},
        export_kw=0.8,   # importing from grid
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=13)
    assert result["targets"]["switch.driveway"] == 0

async def test_plug_in_at_1pm_powerwall_discharge_exceeds_solar_does_not_charge():
    """If battery discharge leaves less than 6A of true solar excess, the car doesn't charge."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.EXCESS_SOLAR},
        export_kw=-2.0,   # 2000W export
        battery_kw=1.5,   # 1500W battery discharge → available = 500W → 2A < min
    )
    result = await run_loop(c, hour=13)
    assert result["targets"]["switch.driveway"] == 0

async def test_plug_in_after_4pm_does_not_charge_even_with_solar():
    """The charging window closes at 4pm; excess-solar mode stops regardless of export."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.EXCESS_SOLAR},
        export_kw=-4.0,   # plenty of solar
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=16)   # 4pm = end of charging window
    assert result["targets"]["switch.driveway"] == 0

async def test_cloud_passes_solar_returns_charging_resumes():
    """If solar export resumes (cloud passes), the next control loop starts charging."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.EXCESS_SOLAR},
        export_kw=-2.4,   # 2400 W → 10 A
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=11)
    assert result["targets"]["switch.driveway"] == 10

async def test_solar_drops_below_minimum_charging_stops():
    """If export falls below what's needed for 6 A minimum, charging stops."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.EXCESS_SOLAR},
        export_kw=-1.0,   # 1000 W / 240 V = 4 A < 6 A minimum
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=11)
    assert result["targets"]["switch.driveway"] == 0

async def test_powerwall_discharging_reduces_solar_charge_rate():
    """If the Powerwall starts discharging, the charge rate is reduced by the battery output
    rather than stopping the session — only solar excess drives the EV."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.EXCESS_SOLAR},
        export_kw=-3.0,   # 3000W export
        battery_kw=1.0,   # 1000W battery discharge → available = 2000W → 8A (not 12A)
    )
    result = await run_loop(c, hour=11)
    assert result["targets"]["switch.driveway"] == 8

# ---------------------------------------------------------------------------
# "Charge Full Speed Off-Peak" button
# ---------------------------------------------------------------------------

async def test_full_speed_offpeak_at_midnight_charges_immediately():
    """Pressing 'Charge Full Speed Off-Peak' after midnight starts charging right away."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.FULL_SPEED_OFFPEAK},
        export_kw=0.5,   # doesn't matter — mode ignores solar
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=0)
    assert result["targets"]["switch.driveway"] == 48

async def test_full_speed_offpeak_stops_at_3pm():
    """'Charge Full Speed Off-Peak' automatically stops when the off-peak window ends at 3pm."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.FULL_SPEED_OFFPEAK},
        export_kw=0.0,
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=15)   # 3pm = OFFPEAK_END_HOUR, exclusive boundary
    assert result["targets"]["switch.driveway"] == 0

async def test_full_speed_offpeak_pauses_when_powerwall_discharges():
    """If the Powerwall starts discharging during off-peak charging, the car pauses."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.FULL_SPEED_OFFPEAK},
        export_kw=0.0,
        battery_kw=1.0,   # discharging
    )
    result = await run_loop(c, hour=1)
    assert result["targets"]["switch.driveway"] == 0

# ---------------------------------------------------------------------------
# "Charge Full Speed Now" (override) button
# ---------------------------------------------------------------------------

async def test_override_charges_after_midnight_regardless_of_solar():
    """'Charge Full Speed Now' works after midnight even with no solar."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.OVERRIDE},
        export_kw=0.5,   # importing
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=0)
    assert result["targets"]["switch.driveway"] == 48

async def test_override_charges_outside_all_windows():
    """'Charge Full Speed Now' ignores all time windows — still charges at 5pm."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.OVERRIDE},
        export_kw=0.5,
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=17)   # outside both charging and off-peak windows
    assert result["targets"]["switch.driveway"] == 48

async def test_override_charges_even_when_powerwall_is_discharging():
    """'Charge Full Speed Now' ignores Powerwall state — it always charges."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.OVERRIDE},
        export_kw=0.0,
        battery_kw=2.0,   # Powerwall discharging
    )
    result = await run_loop(c, hour=14)
    assert result["targets"]["switch.driveway"] == 48

# ---------------------------------------------------------------------------
# "Stop Charging" button
# ---------------------------------------------------------------------------

async def test_stop_charging_halts_even_with_abundant_solar():
    """'Stop Charging' always results in 0 amps regardless of solar or time."""
    c = scenario(
        evse_entities=["switch.driveway"],
        modes={"switch.driveway": ChargeMode.STOPPED},
        export_kw=-10.0,   # tonnes of solar
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=11)
    assert result["targets"]["switch.driveway"] == 0

# ---------------------------------------------------------------------------
# Two EVSEs
# ---------------------------------------------------------------------------

async def test_two_evses_share_solar_current_evenly():
    """With two cars plugged in, available solar current is split evenly."""
    c = scenario(
        evse_entities=["switch.driveway", "switch.garage"],
        modes={
            "switch.driveway": ChargeMode.EXCESS_SOLAR,
            "switch.garage": ChargeMode.EXCESS_SOLAR,
        },
        export_kw=-2.88,   # 2880 W / 240 V = 12 A → 6 A each
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=11)
    assert result["targets"]["switch.driveway"] == 6
    assert result["targets"]["switch.garage"] == 6

async def test_two_evses_neither_charges_when_solar_too_low_to_split():
    """If there isn't enough export to give each EVSE the 6 A minimum, neither charges."""
    c = scenario(
        evse_entities=["switch.driveway", "switch.garage"],
        modes={
            "switch.driveway": ChargeMode.EXCESS_SOLAR,
            "switch.garage": ChargeMode.EXCESS_SOLAR,
        },
        export_kw=-2.0,   # 2000 W / 240 V = 8 A → 4 A each, below 6 A minimum
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=11)
    assert result["targets"]["switch.driveway"] == 0
    assert result["targets"]["switch.garage"] == 0

async def test_stopped_evse_does_not_consume_solar_budget():
    """A stopped EVSE doesn't reduce the current available to a solar-charging EVSE."""
    c = scenario(
        evse_entities=["switch.driveway", "switch.garage"],
        modes={
            "switch.driveway": ChargeMode.STOPPED,
            "switch.garage": ChargeMode.EXCESS_SOLAR,
        },
        export_kw=-2.88,   # 2880 W / 240 V = 12 A — all goes to garage
        battery_kw=0.0,
    )
    result = await run_loop(c, hour=11)
    assert result["targets"]["switch.driveway"] == 0
    assert result["targets"]["switch.garage"] == 12

async def test_evse_without_vehicle_does_not_consume_solar_budget():
    """An EVSE in excess-solar mode with no car plugged in is excluded from current
    allocation, so the other EVSE gets all available solar current."""
    # Real-world case: garage in excess-solar, no car. Driveway has a car.
    # 1650 W export / 240 V = 6.88 A → enough for one EVSE at 6 A minimum,
    # but not two (3 A each < 6 A). Without the fix, neither would charge.
    coordinator = make_coordinator(["switch.driveway", "switch.garage"])
    coordinator._evse_modes = {
        "switch.driveway": ChargeMode.EXCESS_SOLAR,
        "switch.garage": ChargeMode.EXCESS_SOLAR,
    }

    def get_state(entity_id):
        if entity_id == "sensor.site_power":
            return make_state("-1.65")  # 1650 W export
        if entity_id == "sensor.battery":
            return make_state("0.0")
        if entity_id == "switch.garage":
            return make_state("off", {"max_charging_rate": 48, "icon_name": "CarNotConnected"})
        return make_state("on", {"max_charging_rate": 48})  # driveway has car

    coordinator.hass.states.get = MagicMock(side_effect=get_state)

    result = await run_loop(coordinator, hour=11)
    assert result["targets"]["switch.driveway"] == 6
    assert result["targets"]["switch.garage"] == 0


async def test_charging_does_not_chatter_when_consuming_available_solar():
    """Charger already running at 23 A should stay on even though its own draw has
    consumed the apparent site export — the controller reclaims its prior output to
    avoid an off/on/off feedback loop."""
    coordinator = make_coordinator(["switch.driveway"])
    coordinator._evse_modes = {"switch.driveway": ChargeMode.EXCESS_SOLAR}
    # Charger consumed 23 A × 240 V = 5520 W; site now shows only 100 W export
    coordinator._last_targets = {"switch.driveway": 23}

    def get_state(entity_id):
        if entity_id == "sensor.site_power":
            return make_state("-0.1")   # 100 W export — looks nearly zero without reclaim
        if entity_id == "sensor.battery":
            return make_state("0.0")
        return make_state("on", {"max_charging_rate": 48})

    coordinator.hass.states.get = MagicMock(side_effect=get_state)

    result = await run_loop(coordinator, hour=11)
    # Available = 100 W + 23 A × 240 V = 5620 W → 5620 / 240 = 23 A
    assert result["targets"]["switch.driveway"] == 23


async def test_charging_stops_when_solar_genuinely_gone():
    """If solar truly drops (not just consumed by charging), the controller stops the
    charger rather than continuing to draw from the grid."""
    coordinator = make_coordinator(["switch.driveway"])
    coordinator._evse_modes = {"switch.driveway": ChargeMode.EXCESS_SOLAR}
    # Grid is importing 2 kW net — even reclaiming 23 A × 240 V = 5520 W leaves only
    # 5520 - 2000 = 3520 W, which is 14 A.  But if we were at 0 last_targets, nothing to reclaim.
    coordinator._last_targets = {"switch.driveway": 0}  # charger was already off

    def get_state(entity_id):
        if entity_id == "sensor.site_power":
            return make_state("2.0")   # 2 kW import from grid, no solar at all
        if entity_id == "sensor.battery":
            return make_state("0.0")
        return make_state("on", {"max_charging_rate": 48})

    coordinator.hass.states.get = MagicMock(side_effect=get_state)

    result = await run_loop(coordinator, hour=11)
    assert result["targets"]["switch.driveway"] == 0
