# AlexaDeviceManagement

Starter scaffold for a Home Assistant integration to manage Amazon Alexa devices through a dedicated GUI.

## Installation in Home Assistant (HACS)

1. Open **HACS** in Home Assistant.
2. Go to **Integrations** → menu (⋮) → **Custom repositories**.
3. Add this repository URL: `https://github.com/nikodemusz/AlexaDeviceManagement`
4. Select category **Integration** and save.
5. Search for **Alexa Device Management** in HACS and install it.
6. Restart Home Assistant.
7. Go to **Settings → Devices & Services → Add Integration** and add **Alexa Device Management**.

## Manual installation (without HACS)

1. Copy `custom_components/alexa_device_management` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & Services**.

## Structure

```text
custom_components/alexa_device_management/
├── __init__.py
├── config_flow.py
├── const.py
├── manager.py
├── manifest.json
├── panel.py
├── services.yaml
└── www/
    └── alexa-device-management.js
```

## Included

- Home-Assistant Custom Integration (`alexa_device_management`)
- Configuration flow (UI)
- Placeholder service definitions for listing/deleting devices
- Custom panel with basic GUI web component

## Next Steps

- Implement Alexa API integration in `manager.py` (OAuth/token handling)
- Register service handlers and connect them to `manager.py`
- Extend GUI (device list, delete dialog, status messages)
- Optionally add tests for service and API logic
