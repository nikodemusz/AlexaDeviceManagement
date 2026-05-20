# AlexaDeviceManagement

Starter scaffold for a Home Assistant integration to manage Amazon Alexa devices through a dedicated GUI.

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
