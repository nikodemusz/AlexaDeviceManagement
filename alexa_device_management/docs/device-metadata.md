# Native v6 device configuration

The main editor, Lambda discovery and native AddOrUpdateReport all use
`/config/alexa_device_management/native/config.yaml` as their source of truth.
The app manifest `alexa_device_management/config.yaml` is separate.

`/data/alexa_device_management/config.json` retains connection/UI preferences
and the historical `entities` mapping. Its legacy enabled flags never export
anything and never automatically activate native endpoints.

Each key in native `devices` is a stable logical endpoint, externally prefixed
with `native:`. Multiple HA values, such as cistern liters and percentage,
remain capabilities of one device with distinct controller instances. The
device overview can explicitly group selected entities belonging to one HA
device into a named Alexa endpoint, or expose them as separate Alexa endpoints.
The `group_mode`, `ha_device_id`, and `members` fields record combined-group
membership. Capability-level `enabled` flags control individual exported
functions, and `capability_names` provides friendly names for controllers that
need instances, such as each relay in a dual relay. Entities left unchecked in
the grouping editor are removed from the native export; reconciliation then
retires endpoints no longer selected. Endpoint IDs and unrelated capabilities
are preserved.

The editor applies domain-based standard profiles by default. Dimmable lights
use PowerController and BrightnessController, covers use the writable position
RangeController, and climate entities use ThermostatController for mode, target
setpoint and current ambient temperature. Switches use PowerController; their
Alexa display category is suggested as LIGHT, SMARTPLUG or SWITCH from the
entity/device names and class. A simple relay named as a heating valve remains
an on/off switch; a real thermostat requires a climate entity. In the group
editor, explicitly choosing “Eigene Funktionen” stores the selected controller
interfaces and marks them with `capability_mode: custom`. Returning to the
standard profile regenerates its domain defaults.

The native file remains disabled by default on new installations. Existing
native files retain their global and individual activation settings. Selection
is explicit; unsupported new types fail rather than falling back to v5.

Validate metadata with `schemas/native-skill.schema.json` and
`NativeSkillConfigStore.validate`. The runtime rejects more than 300 active
endpoints; disabled drafts do not count toward that limit. Native writes are
atomic and the editor requires a current revision to prevent lost updates.
No credentials, tokens or private endpoints belong in device metadata.

See [v6 deployment](dual-skill-deployment.md) for AWS and HA upgrade steps.
