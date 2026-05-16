# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**emporia-controller** is an EV charging controller that manages Emporia EVSEs based on home solar production and Powerwall state. It integrates with Home Assistant (and subsequently HomeKit).

**"Excess solar"** = the home energy system is exporting energy to the grid.

## Core Behaviors

### Default (excess solar mode)
- Charge vehicles only when exporting to grid (excess solar)
- Pause charging when Powerwalls are discharging
- Charging window: midnight–4pm local time only

### User-Facing Controls (per EVSE in Home Assistant)
1. Charge at full speed off-peak (midnight–3pm)
2. Charge at full speed now (override — ignores time/solar)
3. Charge on excess solar (default)
4. Stop all charging sessions

### Edge Cases
- Powerwall discharging + before 4pm → stop EVSEs
- User requests full-speed while on excess solar → switch to full-speed
- Multiple EVSEs offering charge simultaneously → split available current evenly across them
- Vehicle requesting less than offered current → offer the difference to other EVSEs

## Hard Constraints

- **J1772 compliance**: minimum charge rate is 6 amps (1440W)
- **Control loop**: must not run more frequently than every 15 seconds
- **State persistence**: survive application restarts; fall back to default behavior if state cannot be recovered
- **Integration**: Tesla Powerwall plugin via Home Assistant; HomeKit via Home Assistant

## Implementation

**Home Assistant custom component** (Python). Lives in `custom_components/emporia_controller/`.

- Async control loop (15s minimum interval) reads Powerwall state + grid export sensor, computes target current, calls Emporia EVSE service
- State machine per EVSE (`excess_solar` / `full_speed` / `override` / `stopped`) persisted via HA `.storage` helper
- Current allocation: total available amps ÷ active EVSE count, floored at 6A minimum per EVSE
- User controls exposed as native HA entities

## Configuration Options

Set at install time and reconfigurable via Settings → Devices & Services → Emporia EVSE Controller → Configure. No entity IDs are hardcoded.

| Option | Key | Description |
|---|---|---|
| EVSE charger entities | `evse_entities` | Emporia switch entities for each EV charger |
| Site power sensor | `site_power_sensor` | kW sensor; negative = exporting to grid (excess solar) |
| Battery power sensor | `battery_power_sensor` | kW sensor; positive = discharging |
| Circuit voltage | `voltage` | Charger circuit voltage (default 240V) |
| Enable debug logging | `debug_logging` | Log detailed controller decisions to HA log |
| Disable controller | `disabled` | Pause all activity without removing the integration |
| Reset charge mode state | `reset_state` | Clear persisted charge mode; returns to defaults on next restart |

## Home Assistant Entities

**EVSEs:** Emporia EVSE switch entities — controlled via `switch.turn_on/off` + `emporia_vue.set_charger_current`. Max charge rate is read from the `max_charging_rate` attribute on the switch entity.

**Site power sensor:** kW, **negative = exporting to grid** (excess solar).

**Battery power sensor:** kW, **positive = discharging**.

**EVSE control:**
- Stop: `switch.turn_off {entity_id}`
- Set rate: `emporia_vue.set_charger_current {entity_id, current}` (min 6A, max 48A), then `switch.turn_on`

## Development

Requires Python 3.10+.

| Command | Effect |
|---|---|
| `make test` | Run pylint then pytest (full CI check) |
| `make lint` | Pylint only |
| `make clean` | Delete the venv |

Tests run without a live HA install — `tests/conftest.py` stubs out the entire `homeassistant` package. Pylint config is in `.pylintrc` (max line length 120, docstrings and HA import errors suppressed).

## Deployment

HA credentials (URL + long-lived API token) are stored in `.ha_credentials` at the repo root (gitignored). Copy `.ha_credentials.template` and fill in the values to set it up. Read credentials from there before running any deploy commands.

The integration is installed in HA via HACS and tracked by the update entity `update.emporia_evse_controller_update`. To deploy after pushing a commit:

**1. Install the new version via HACS:**
```bash
curl -s -X POST \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "update.emporia_evse_controller_update", "version": "<commit-hash>"}' \
  "$HA_URL/api/services/update/install"
```

**2. Restart HA:**
```bash
curl -s -X POST \
  -H "Authorization: Bearer $HA_TOKEN" \
  "$HA_URL/api/services/homeassistant/restart"
```

**3. Wait for HA to come back up and confirm:**
```bash
until curl -s -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/" 2>/dev/null | grep -q message; do sleep 5; done
curl -s -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/states/update.emporia_evse_controller_update" \
  | python3 -c "import json,sys; a=json.load(sys.stdin)['attributes']; print('installed:', a['installed_version'])"
```
