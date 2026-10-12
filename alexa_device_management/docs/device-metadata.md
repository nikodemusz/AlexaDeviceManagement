# Native v6 device configuration

The main editor, Lambda discovery and native AddOrUpdateReport all use
`/config/alexa_device_management/native/config.yaml` as their source of truth.
The app manifest `alexa_device_management/config.yaml` is separate.

`/data/alexa_device_management/config.json` retains connection/UI preferences
and the historical `entities` mapping. Its legacy enabled flags never export
anything and never automatically activate native endpoints.

Each key in native `devices` is a stable logical endpoint, externally prefixed
with `native:`. Multiple HA values, such as cistern liters and percentage,
remain capabilities of one device with distinct controller instances. Selecting
or renaming one bound entity in the editor updates that complete logical device.
Endpoint IDs and existing capabilities are preserved.

The native file remains disabled by default on new installations. Existing
native files retain their global and individual activation settings. Selection
is explicit; unsupported new types fail rather than falling back to v5.

Validate metadata with `schemas/native-skill.schema.json` and
`NativeSkillConfigStore.validate`. The runtime rejects more than 300 active
endpoints; disabled drafts do not count toward that limit. Native writes are
atomic and the editor requires a current revision to prevent lost updates.
No credentials, tokens or private endpoints belong in device metadata.

See [v6 deployment](dual-skill-deployment.md) for AWS and HA upgrade steps.
