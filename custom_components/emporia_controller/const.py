DOMAIN = "emporia_controller"

UPDATE_INTERVAL_SECONDS = 15
MIN_CHARGE_AMPS = 6
DEFAULT_MAX_AMPS = 48
DEFAULT_VOLTAGE = 240
BATTERY_DISCHARGE_THRESHOLD_KW = 0.1
SOLAR_RATE_STEP_AMPS = 2  # max amps to increase per control loop iteration in solar mode

# Charging allowed midnight–4pm local time (exclusive end)
CHARGING_WINDOW_START_HOUR = 0
CHARGING_WINDOW_END_HOUR = 16

# Full-speed off-peak window midnight–3pm local time (exclusive end)
OFFPEAK_END_HOUR = 15

CONF_EVSE_ENTITIES = "evse_entities"
CONF_SITE_POWER_SENSOR = "site_power_sensor"
CONF_BATTERY_POWER_SENSOR = "battery_power_sensor"
CONF_VOLTAGE = "voltage"
CONF_DEBUG_LOGGING = "debug_logging"
CONF_RESET_STATE = "reset_state"
CONF_DISABLED = "disabled"

STORAGE_KEY = f"{DOMAIN}.state"
STORAGE_VERSION = 1

class ChargeMode:
    EXCESS_SOLAR = "excess_solar"
    FULL_SPEED_OFFPEAK = "full_speed_offpeak"
    OVERRIDE = "override"
    STOPPED = "stopped"
