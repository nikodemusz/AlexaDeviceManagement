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

### Native v6 main editor

- Select HA entities and configure native Alexa names/categories directly.
- Keep stable logical endpoint IDs and multiple values per device.
- Validate and atomically save the authoritative native YAML with revision protection.
- Publish complete v6 AddOrUpdateReport batches; retry errors without claiming success.
- Automatically retire confirmed HA-v5 devices and verify with fresh inventory.
- Count native endpoints, with old copies excluded from native synchronization counts.

The native YAML is `/config/alexa_device_management/native/config.yaml`.
`/data/alexa_device_management/config.json` retains UI/event settings and archived
v5 entities, which never export or activate devices. The migration page is retired.
See [3.0 upgrade steps](docs/dual-skill-deployment.md).

## Installation

1. Open **Settings → Add-ons → Add-on Store** in Home Assistant OS.
2. Open the menu (⋮) and choose **Repositories**.
3. Add `https://github.com/nikodemusz/AlexaDeviceManagement`.
4. Install and start **Alexa Device Management**.
5. Open **Alexa Devices** from the sidebar.

## Upgrade from 2.x

Install the new app, deploy the native-only AWS Lambda separately, install the
updated HA sync helper and deny-all v5 YAML, restart HA when requested, and verify
native publication and automatic v5 retirement. Do not disable the shared skill.
Existing v6 activation is preserved; no legacy devices are auto-imported.

## Development validation

See [Discovery, control, and status tests](docs/testing-native-devices.md) for the
offline Lambda-to-gateway contract suite and ready-to-copy AWS console events.

The CI workflow performs:

- Python compilation
- Unit tests
- JavaScript syntax checks
- App metadata validation
- Docker image build

## Release notes

See [CHANGELOG.md](./CHANGELOG.md) and the fragments under [`CHANGELOG.d`](./CHANGELOG.d/).
