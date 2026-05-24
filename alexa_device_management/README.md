# AlexaDeviceManagement

A Home Assistant custom integration for managing Amazon Alexa devices through a dedicated panel UI — analogous to Z-Wave JS UI or Zigbee2MQTT.

**Note:** For Home Assistant OS App Installer installation, use the repository install flow from the root `README.md` and run the **Alexa Device Management Installer** app once before adding the integration.

Home Assistant serves as the application platform (authentication, external URL access, sidebar navigation). The integration provides a full device management experience accessible locally and remotely.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Home Assistant (Platform / Host)                │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  Custom Panel (Sidebar)                   │   │
│  │  alexa-device-management.js               │   │
│  │  • Device grid / list view                │   │
│  │  • Device detail view                     │   │
│  │  • Rename / Delete actions                │   │
│  └──────────────┬───────────────────────────┘   │
│                 │ WebSocket API                   │
│  ┌──────────────▼───────────────────────────┐   │
│  │  websocket_api.py                         │   │
│  │  • list_devices / get_device              │   │
│  │  • delete_device / rename_device          │   │
│  │  • refresh_devices / subscribe            │   │
│  └──────────────┬───────────────────────────┘   │
│                 │                                 │
│  ┌──────────────▼───────────────────────────┐   │
│  │  manager.py (AlexaDeviceManager)          │   │
│  │  • Connection state machine               │   │
│  │  • Device cache                           │   │
│  │  • Alexa API calls (TODO: OAuth)          │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

## Features

- **Sidebar panel** — accessible via HA navigation, works with external URL
- **WebSocket API** — real-time communication between frontend and backend
- **Device list** — grid view with online/offline status
- **Device details** — type, serial, firmware, capabilities, room
- **Device actions** — rename, delete
- **Event subscriptions** — frontend auto-updates on changes (push, no polling)
- **Connection state** — visual indicator for API connection status

## Installation (HACS)

1. Open **HACS** in Home Assistant.
2. Go to **Integrations** → menu (⋮) → **Custom repositories**.
3. Add this repository URL: `https://github.com/nikodemusz/AlexaDeviceManagement`
4. Select category **Integration** and save.
5. Search for **Alexa Device Management** in HACS and install it.
6. Restart Home Assistant.
7. Go to **Settings → Devices & Services → Add Integration** and add **Alexa Device Management**.

## Manual Installation

1. Copy `custom_components/alexa_device_management` into your HA `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & Services**.

## Structure

```text
custom_components/alexa_device_management/
├── __init__.py          # Entry point, wires manager + WS API + panel
├── config_flow.py       # Setup dialog
├── const.py             # Constants (domain, events, states)
├── manager.py           # Device manager (connection, cache, API)
├── manifest.json        # HA integration metadata
├── panel.py             # Sidebar panel registration
├── services.yaml        # Service definitions
├── strings.json         # UI strings
├── websocket_api.py     # WebSocket command handlers
└── www/
    └── alexa-device-management.js   # Frontend panel (SPA)
```

## WebSocket Commands

| Command | Description |
|---------|-------------|
| `alexa_device_management/connection_state` | Get current connection state |
| `alexa_device_management/list_devices` | List all devices |
| `alexa_device_management/get_device` | Get single device details |
| `alexa_device_management/delete_device` | Delete a device |
| `alexa_device_management/rename_device` | Rename a device |
| `alexa_device_management/refresh_devices` | Re-fetch from Alexa API |
| `alexa_device_management/subscribe` | Subscribe to real-time events |

## Next Steps

- [ ] Implement Alexa API OAuth2 authentication in config flow
- [ ] Replace demo devices with real Alexa API calls in `manager.py`
- [ ] Add device grouping by room
- [ ] Add Do-Not-Disturb / volume controls
- [ ] Add routine management
- [ ] Add multi-room music group management
