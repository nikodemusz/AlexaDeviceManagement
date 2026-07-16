# Home Assistant Apps by nikodemusz

This repository contains Home Assistant apps by nikodemusz.

Apps documentation: <https://developers.home-assistant.io/docs/apps>

[![Open your Home Assistant instance and show the app store with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/?repository_url=https%3A%2F%2Fgithub.com%2Fnikodemusz%2FAlexaDeviceManagement)

## Apps

| App | Description |
|-----|-------------|
| [Alexa Device Management](./alexa_device_management/) | Manage Amazon Alexa devices and configure which Home Assistant entities are exposed through a manual Alexa Smart Home skill |

## Alexa Device Management 2.8 RC

The app contains two independent work areas:

- **Alexa device inventory**: list, rename and bulk-delete devices already stored in Alexa.
- **HA → Alexa designer**: select Home Assistant entities, edit Alexa names and categories, preview discovery, validate consistency and deploy `/config/packages/alexa.yaml` with rollback.

The HA export manager does not require an Amazon login. Its persistent source of truth is `/data/alexa_device_management/config.json`. Existing state from `/data/ha_alexa_export.json` or `/config/packages/alexa.yaml` is imported automatically. Deployments are written atomically, checked through Home Assistant and rolled back on validation failure. The ten newest YAML backups are retained.

## Upgrade from 1.x

1. Update and start the app.
2. Open **HA → Alexa** once to migrate the previous editor state or import the existing `packages/alexa.yaml`.
3. Run **Discovery-Vorschau** and **Konsistenz prüfen**.
4. Deploy the configuration. The previous YAML remains available as a backup.
5. Restart Home Assistant when requested and run Alexa device discovery.

The Alexa web session and existing Alexa device cache remain separate from the HA export configuration.

## Installation

1. Open **Settings → Add-ons → Add-on Store** in Home Assistant OS.
2. Open the menu (⋮) and choose **Repositories**.
3. Add this repository URL: `https://github.com/nikodemusz/AlexaDeviceManagement`.
4. Install **Alexa Device Management** and start it.
5. Open **Alexa Devices** from the HA sidebar.
6. Use **HA → Alexa** in the toolbar to configure the manual Home Assistant Alexa skill export.

## Release validation

Pull requests run Python compilation, unit tests, JavaScript syntax checks, app metadata validation and a complete Docker image build.
