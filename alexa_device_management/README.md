# Alexa Device Management

A standalone Home Assistant OS app that provides a web UI for managing Amazon Alexa
smart home devices — a replacement for Amazon's removed bulk-management web interface.

This is **not** a Home Assistant integration. It is a standalone app that runs its own
web server inside a Docker container and is accessible via the HA sidebar (ingress).
It has nothing to do with HA entities or the device registry.

## Why?

Amazon removed their web UI that allowed users to manage Alexa devices in bulk
(rename, delete, reorganize rooms, etc.). The Alexa phone app only supports
one-device-at-a-time management, which is impractical for users with many devices.
This app brings back efficient bulk device management.

## Features

- View all your Amazon Alexa devices in a clean web UI
- Accessible as a sidebar menu item in Home Assistant OS
- Runs as a standalone Docker container (no HA integration needed)
- Configuration via add-on settings (Amazon OAuth2 credentials)

## Installation

1. Open **Settings → Add-ons → Add-on Store** in Home Assistant OS.
2. Open the menu (⋮) and choose **Repositories**.
3. Add: `https://github.com/nikodemusz/AlexaDeviceManagement`
4. Install **Alexa Device Management** and start it.
5. Open **Alexa Devices** from the sidebar.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Home Assistant OS                               │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  Alexa Device Management (Add-on/App)    │   │
│  │                                           │   │
│  │  ┌─────────────────────────────────────┐ │   │
│  │  │  Python Web Server (aiohttp)        │ │   │
│  │  │  • Serves HTML/CSS/JS UI            │ │   │
│  │  │  • REST API for device data         │ │   │
│  │  │  • Communicates with Amazon API     │ │   │
│  │  └─────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ← Ingress (sidebar panel "Alexa Devices") →    │
└─────────────────────────────────────────────────┘
```

## Next Steps

- [ ] Bulk delete devices
- [ ] Bulk rename devices
- [ ] Room management
- [ ] Do-Not-Disturb controls
