# Home Assistant Apps by nikodemusz

This repository contains Home Assistant apps by nikodemusz.

Apps documentation: <https://developers.home-assistant.io/docs/apps>

[![Open your Home Assistant instance and show the app store with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/?repository_url=https%3A%2F%2Fgithub.com%2Fnikodemusz%2FAlexaDeviceManagement)

## Apps

| App | Description |
|-----|-------------|
| [Alexa Device Management](./alexa_device_management/) | Web UI for managing Amazon Alexa smart-home devices and configuring which Home Assistant entities are exposed through a manual Alexa Smart Home skill |

## Alexa Device Management 1.4

The app contains two independent areas:

- **Alexa device inventory**: list, rename and bulk-delete devices already stored in Alexa.
- **HA → Alexa export manager**: read Home Assistant devices, entities and areas; select useful entities; edit Alexa names and categories; preview and generate `/config/packages/alexa.yaml`.

The HA export manager does not require an Amazon login. It uses the Home Assistant API available to the app and stores its editor state in `/data/ha_alexa_export.json`. Existing `packages/alexa.yaml` selections are imported automatically on first use. Before writing, the current YAML file is backed up.

## Installation (HA OS App Installer)

1. Open **Settings → Add-ons → Add-on Store** in Home Assistant OS.
2. Open the menu (⋮) and choose **Repositories**.
3. Add this repository URL: `https://github.com/nikodemusz/AlexaDeviceManagement`.
4. Install **Alexa Device Management** and start it.
5. Open **Alexa Devices** from the HA sidebar.
6. Use **HA → Alexa** in the toolbar to configure the manual Home Assistant Alexa skill export.
