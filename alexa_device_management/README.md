# Alexa Device Management

A standalone Home Assistant OS app for managing Amazon Alexa smart-home devices and designing the Home Assistant entities exposed through a manual Alexa Smart Home skill.

This is not a Home Assistant integration. It runs as its own app with an ingress web interface.

## Main areas

### Alexa inventory

- List Echo and smart-home devices
- Filter and sort large inventories
- Rename supported devices
- Bulk-delete devices
- Export filtered results as CSV
- Cache Alexa inventory with background refresh
- Inspect raw responses in the debug console

### Home Assistant → Alexa designer

- Read devices, entities, areas and floors from Home Assistant
- Configure Alexa names, descriptions and display categories
- Responsive entity cards for desktop, tablet and mobile
- Autosave and bulk editor
- Discovery preview with duplicate-name and orphan detection
- Consistency and permission checks
- Deterministic YAML generation from persistent `config.json`
- Atomic deployment to `/config/packages/alexa.yaml`
- Full Home Assistant configuration validation and automatic rollback
- Persistent deploy, restart and Alexa-discovery lifecycle status

## Data and migration

The designer stores its source configuration in:

```text
/data/alexa_device_management/config.json
```

On first use, it can migrate the previous editor state from:

```text
/data/ha_alexa_export.json
```

If neither state file exists, an existing `/config/packages/alexa.yaml` is imported. The Alexa login session and Alexa device cache are not replaced by this migration.

Deployments retain the ten newest backups next to `alexa.yaml`. A failed Home Assistant configuration check restores the previous file automatically.

## Installation

1. Open **Settings → Add-ons → Add-on Store** in Home Assistant OS.
2. Open the menu (⋮) and choose **Repositories**.
3. Add `https://github.com/nikodemusz/AlexaDeviceManagement`.
4. Install and start **Alexa Device Management**.
5. Open **Alexa Devices** from the sidebar.

## Recommended upgrade procedure from 1.x

1. Update the app and open **HA → Alexa**.
2. Verify the imported entities.
3. Run **Discovery-Vorschau**.
4. Run **Konsistenz prüfen**.
5. Deploy the configuration.
6. Restart Home Assistant when the lifecycle status requests it.
7. Start Alexa device discovery and mark it completed in the app.

## Development validation

The CI workflow performs:

- Python compilation
- Unit tests
- JavaScript syntax checks
- App metadata validation
- Docker image build

## Release notes

See [CHANGELOG.md](./CHANGELOG.md) and the fragments under [`CHANGELOG.d`](./CHANGELOG.d/).
