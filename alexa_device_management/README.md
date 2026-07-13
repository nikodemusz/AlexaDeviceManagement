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

- View all your Amazon Alexa devices (Echo and smart home) in a clean, filterable table
- Rename devices directly from the table (Echo devices and smart home devices)
- Bulk delete: select multiple devices and remove them from Alexa in one action
- Sortable columns and per-column filters (name, type, skill/connector, manufacturer, room, source, online status)
- CSV export of the currently filtered device list
- Amazon Web Login helper for creating and storing the Alexa web session
- Built-in debug console (`/debug`) for inspecting the raw Alexa API responses
- Accessible as a sidebar menu item in Home Assistant OS
- Runs as a standalone Docker container (no HA integration needed)

## Installation

1. Open **Settings → Add-ons → Add-on Store** in Home Assistant OS.
2. Open the menu (⋮) and choose **Repositories**.
3. Add: `https://github.com/nikodemusz/AlexaDeviceManagement`
4. Install **Alexa Device Management** and start it.
5. Open **Alexa Devices** from the sidebar.

## Release Notes

See [CHANGELOG.md](./CHANGELOG.md) for version-specific release notes.

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

## Feature Status

- [x] Device list (Echo + smart home) with filters and sorting
- [x] Bulk delete devices
- [x] Rename devices
- [x] CSV export
- [ ] Room management (possible future extension)
- [ ] Do-Not-Disturb controls (possible future extension)
