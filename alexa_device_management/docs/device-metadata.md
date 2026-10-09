# Device metadata schema v6 (Sprint 1)

Configuration source: `/data/alexa_device_management/config.json`.
The existing `entities` object and HA Alexa YAML deployment are retained unchanged for backwards compatibility.
The new `devices` object is **not yet deployed to Amazon**. It is groundwork for a custom Smart Home skill.

## Model

Each key under `devices` is a durable Alexa endpoint ID (not an HA entity ID).
A device has a human-readable `name`, optional `aliases`, `description`, `display_category`, `enabled`, and a list of `capabilities`.
Each capability binds an Alexa `interface` to exactly one existing Home Assistant `entity_id`.
Multiple capabilities may reference the same entity, and multiple entities may share a device.

Supported model interfaces: `Alexa.PowerController`, `Alexa.BrightnessController`, `Alexa.RangeController`, `Alexa.ToggleController`.
Each RangeController and ToggleController needs an `instance`; instance identifiers must be unique within their interface for the same device.
Read-only RangeControllers require a `unit`. Units in the examples are *intended* Alexa units and will be validated against Amazon's supported unit catalog in the implementation of the actual skill.
Alexa voice interpretation and unsupported interface/display-category combinations are not guaranteed by this metadata schema.

## Example

```json
{
  "schema_version": 6,
  "entities": {},
  "devices": {
    "zisterne": {
      "name": "Zisterne",
      "aliases": ["meine Zisterne", "Wassertank"],
      "display_category": "OTHER",
      "enabled": true,
      "capabilities": [
        {"interface": "Alexa.RangeController", "instance": "volume", "entity_id": "sensor.zisterne_liter", "unit": "Volume.Liters", "read_only": true},
        {"interface": "Alexa.RangeController", "instance": "fill", "entity_id": "sensor.zisterne_prozent", "unit": "Percent", "read_only": true},
        {"interface": "Alexa.ToggleController", "instance": "pump", "entity_id": "switch.zisternenpumpe"}
      ]
    },
    "living_light": {
      "name": "Wohnzimmerlicht",
      "display_category": "LIGHT",
      "capabilities": [
        {"interface": "Alexa.PowerController", "entity_id": "light.wohnzimmer"},
        {"interface": "Alexa.BrightnessController", "entity_id": "light.wohnzimmer"},
        {"interface": "Alexa.RangeController", "instance": "watts", "entity_id": "sensor.wohnzimmer_watt", "unit": "Power.Watts", "read_only": true}
      ]
    }
  }
}
```

## Migration from v5

On load/save, enabled legacy `entities` are copied conservatively to separate `ha:<entity_id>` devices if the config has no `devices` field.
Lights and switches get a PowerController binding; other entity domains get no guessed capability.
The original `entities` settings are retained byte-for-byte at the object level (the JSON file itself is normalized by the existing store).
An explicit `devices: {}` intentionally opts out of automatic migration.
Re-running normalization does not add or duplicate endpoints.
Grouping multiple sensor entities under a single endpoint is an explicit subsequent edit.

## AI-agent checklist

1. Inspect the actual entity IDs, state and units from Home Assistant. Do not invent them.
2. Look for an existing logical device before adding a new endpoint ID.
3. Reuse the same endpoint for all related properties; unique controller instances.
4. Validate with `schemas/device-config.schema.json` and the Python runtime validator before writing.
5. Save atomically through the ConfigStore, keeping legacy `entities` intact.
6. Inspect preview output before a deployment; Sprint 1's device preview is internal only.
