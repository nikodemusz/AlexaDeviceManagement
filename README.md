# Home Assistant Apps by nikodemusz

This repository contains Home Assistant apps by nikodemusz.

Apps documentation: <https://developers.home-assistant.io/docs/apps>

[![Open your Home Assistant instance and show the app store with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/?repository_url=https%3A%2F%2Fgithub.com%2Fnikodemusz%2FAlexaDeviceManagement)

## Apps

| App | Description |
|-----|-------------|
| [Alexa Device Management](./alexa_device_management/) | Manage Amazon Alexa devices and configure which Home Assistant entities are exposed through a manual Alexa Smart Home skill |

## Alexa Device Management 3.0

The main device editor configures native v6 endpoints in
`/config/alexa_device_management/native/config.yaml`. No v5 device is exported.
Historical JSON is retained as an archive plus UI/connection preferences.

Native lifecycle reports publish the same endpoints as Lambda Discovery.
Positively identified old HA-v5 devices are automatically removed from Alexa;
selected native endpoints, Echos and unrelated devices are protected. Unselected
managed native endpoints are removed even without prior publication records. The migration page
is retired. See [deployment/upgrade steps](alexa_device_management/docs/dual-skill-deployment.md).

## Installation

1. Open **Settings → Add-ons → Add-on Store** in Home Assistant OS.
2. Open the menu (⋮) and choose **Repositories**.
3. Add this repository URL: `https://github.com/nikodemusz/AlexaDeviceManagement`.
4. Install **Alexa Device Management** and start it.
5. Open **Alexa Devices** from the HA sidebar.
6. Open the main device editor and follow the v6 deployment/upgrade steps.

## Release validation

Pull requests run Python compilation, unit tests, JavaScript syntax checks, app metadata validation and a complete Docker image build.
