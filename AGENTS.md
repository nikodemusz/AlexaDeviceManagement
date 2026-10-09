# Agent instructions – Alexa Device Management

- Read `alexa_device_management/docs/device-metadata.md` and `alexa_device_management/schemas/device-config.schema.json` before editing device metadata.
- **Separate source of truth**: legacy export uses `/data/alexa_device_management/config.json`; the new independent Smart Home skill uses `/config/alexa_device_management/native/config.yaml`. Never change one when editing the other. The legacy `entities` mapping MUST remain available.
- The HA app manifest at `alexa_device_management/config.yaml` is NOT the new skill configuration. Do not overwrite it.
- The native YAML config defaults to `enabled: false`; no automatic activation, migration, or AWS deployment. Read `alexa_device_management/schemas/native-skill.schema.json` before editing it.
- Schema v6 adds `devices`: one stable endpoint ID per logical device, multiple Alexa capabilities, each bound to a Home Assistant entity.
- Never create one Alexa device per sensor when several values belong to one logical device. Reuse endpoint IDs and use unique `instance` values for additional Range/Toggle controllers.
- Capability support in Sprint 1 is a *model/validation contract*, not deployed Alexa discovery. Do not imply tested voice support without an actual device test.
- Never store credentials, OAuth tokens, access keys or personal endpoints in source-controlled metadata.
- Before saving native skill metadata, validate against `schemas/native-skill.schema.json` and `native_skill_config.NativeSkillConfigStore.validate`; the shared device model is checked by the store. Never store credential material.
- Keep `schema_version`, migration behavior, examples, and tests aligned. Do not silently discard unknown existing legacy data.
- Run `python -m unittest discover -s alexa_device_management/tests` and syntax checks before requesting merge.
- Follow semantic versioning: +0.0.1 fixes, +0.1.0 features, +1.0.0 milestones; update the short changelog for grouped commits.
- Do not merge pull requests without explicit user approval.
