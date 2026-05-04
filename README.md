# emporia-contorller

Definitions:
* excess solar is a term used to define when the home energy system is exporting energy to the grid

Emporia EVSE controller that has the following behavior:
* default behavior for the EVSEs is to charge vehicles on excess solar
* default behavior detects when the powerwalls are discharging and disables EV charging
* only charges the vehicles between midnight and 4pm local-time
* integrates with home assistant and subsequently homekit
* integrates with the tesla powerwall plugin in home assistant
* control loop should run no more frequently than 15 seconds
* charging should comply with J1772 standards, including that the minimum charge rate is 6 amps (1440w)
* maintain state/behavior between application restarts
* if no state/behavior can be retained between application restarts, the controller should follow the defualt behavior above

Edge case behavior:
* if the system is discharging the powerwalls and the time is before 4pm, EVSEs should stop charging
* if the vehicle is charging from excess solar and a user requests full-speed charging, then the EVSEs should change to that setting.
* if more than one EVSE is connected to more than one vehicle and offering a charge to those vehicles, the available current should be split evenly between the remaining EVSEs
* if one vehicle is asking for less current than offered by an EVSE, it should offer that difference in current to other EVSEs

For each emporia EVSE in home assistant, it provides the following buttons/controls for users in home-assistant:
* charge at full speed off-peak hours between midnight and 3pm
* charge at full speed now regardless of timeframe (an override)
* charge on excess solar
* stop all current charging sessions
