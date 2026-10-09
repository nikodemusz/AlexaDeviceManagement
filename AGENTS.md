# Agent instructions – Alexa Device Management

- Read `alexa_device_management/docs/device-metadata.md` and `alexa_device_management/schemas/device-config.schema.json` before editing device metadata.
- The source of truth is `/data/alexa_device_management/config.json`. The legacy `entities` mapping MUST remain available to the existing Home Assistant YAML exporter.
- Schema v6 adds `devices`: one stable endpoint ID per logical device, multiple Alexa capabilities, each bound to a Home Assistant entity.
- Never create one Alexa device per sensor when several values belong to one logical device. Reuse endpoint IDs and use unique `instance` values for additional Range/Toggle controllers.
- Capability support in Sprint 1 is a *model/validation contract*, not deployed Alexa discovery. Do not imply tested voice support without an actual device test.
- Never store credentials, OAuth tokens, access keys or personal endpoints in source-controlled metadata.
- Before saving metadata, validate against the JSON Schema and the Python `device_model.validate_devices` runtime checks.
- Keep `schema_version`, migration behavior, examples, and tests aligned. Do not silently discard unknown existing legacy data.
- Run `python -m unittest discover -s alexa_device_management/tests` and syntax checks before requesting merge.
- Follow semantic versioning: +0.0.1 fixes, +0.1.0 features, +1.0.0 milestones; update the short changelog for grouped commits.
- Do not merge pull requests without explicit user approval.
