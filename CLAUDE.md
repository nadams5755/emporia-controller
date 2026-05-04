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

## Home Assistant Entities

All entity IDs are user-configured at setup time (and reconfigurable via Settings → Devices & Services → Configure). No entity IDs are hardcoded.

**EVSEs:** Emporia EVSE switch entities — controlled via `switch.turn_on/off` + `emporia_vue.set_charger_current`. Max charge rate is read from the `max_charging_rate` attribute on the switch entity.

**Site power sensor:** kW, **negative = exporting to grid** (excess solar).

**Battery power sensor:** kW, **positive = discharging**.

**EVSE control:**
- Stop: `switch.turn_off {entity_id}`
- Set rate: `emporia_vue.set_charger_current {entity_id, current}` (min 6A, max 48A), then `switch.turn_on`
