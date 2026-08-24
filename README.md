# emporia-controller

## Installation with HACS

Requires the [ha-emporia-vue custom component](https://github.com/magico13/ha-emporia-vue).  i've only tested this with [the tesla powerwall integration](https://www.home-assistant.io/integrations/powerwall/)  but i don't see why it wouldn't work with other sources.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)

hat tip to [magico13](https://github.com/magico13) for these instructions.

The simplest way to install this integration is with the Home Assistant Community Store (HACS). This is not (yet) part of the default store and will need to be added as a custom repository.

Setting up a custom repository is done by:

1. Go into HACS from the side bar.
2. Click into Integrations.
3. Click the 3-dot menu in the top right and select `Custom repositories`
4. In the UI that opens, copy and paste the [url for this github repo](https://github.com/nadams5755/emporia-controller) into the `Add custom repository URL` field.
5. Set the category to `Integration`.
6. Click the `Add` button.
7. Select Emporia Vue from the list and press the download button.
8. Further configuration is done within the Integrations configuration in Home Assistant. You may need to restart home assistant and clear your browser cache before it appears, try ctrl+shift+r if you don't see it in the configuration list.

## Configuration

Configuration is done directly in the Home Assistant UI, no manual config file editing is required.

1. Go into the Home Assistant `Configuration`
2. Select `Integrations`
3. Click the `+` button at the bottom
4. Search for "Emporia EVSE Controller" and add it. If you do not see it in the list, ensure that you have installed the integration.
5. Fill in the configuration fields:

| Field | Description |
|---|---|
| **EVSE charger entities** | The Emporia switch entities for each EV charger (e.g. `switch.garage`, `switch.driveway`) |
| **Site power sensor** | Sensor reporting total site power in kW — negative values mean exporting to the grid (excess solar) |
| **Battery power sensor** | Sensor reporting battery power in kW — positive values mean the battery is discharging |
| **Circuit voltage** | Voltage of the EV charger circuits (typically 240V for residential) |
| **Enable debug logging** | Log detailed controller decisions to the Home Assistant log |
| **Disable controller** | Pause all controller activity without removing the integration |
| **Reset charge mode state** | Clear saved charge mode for all EVSEs and return to defaults on next restart |

The last three fields are primarily useful after initial setup and are accessible at any time via **Settings → Devices & Services → Emporia EVSE Controller → Configure**.

## tl;dr

Definitions:
* excess solar is a term used to define when the home energy system is exporting energy to the grid

Emporia EVSE controller that has the following behavior:
* default behavior for the EVSEs is to charge vehicles on excess solar
* default behavior detects when the powerwalls are discharging and ramp down the charge rate until the powerwalls stop discharging or the charge rate is zero.
* only charges the vehicles between midnight and 4pm local-time
* integrates with home assistant and subsequently homekit
* integrates with the tesla powerwall plugin in home assistant
* control loop should run no more frequently than 15 seconds
* charging should comply with J1772 standards, including that the minimum charge rate is 6 amps (1440w)
* maintain state/behavior between application restarts
* if no state/behavior can be retained between application restarts, the controller should follow the defualt behavior above

Edge case behavior:
* if the system is discharging the powerwalls and the time is before 4pm, EVSEs should ramp down the charge rate until the powerwalls stop discharging or the charge rate is zero
* if the vehicle is charging from excess solar and a user requests full-speed charging, then the EVSEs should change to that setting.
* if more than one EVSE is connected to more than one vehicle and offering a charge to those vehicles, the available current should be split evenly between the remaining EVSEs
* if one vehicle is asking for less current than offered by an EVSE, it should offer that difference in current to other EVSEs

For each emporia EVSE in home assistant, it provides the following buttons/controls for users in home-assistant:
* charge at full speed off-peak hours between midnight and 3pm
* charge at full speed now regardless of timeframe (an override)
* charge on excess solar

There is no separate "stop charging" control — the EVSE's own switch entity is already stateful, and the controller re-asserts its computed charge state every control loop cycle, so a manual toggle of that switch won't stick. To hand control of the switches back to Home Assistant/HomeKit directly, use the **Disable controller** option, which pauses all controller activity.

## Running the tests

Requires Python 3.10+. The first run creates a virtual environment and installs dependencies automatically.

```
make test
```

To force a clean rebuild of the virtual environment:

```
make clean && make test
```
