# Alexa Device Management

Standalone web UI to manage your Amazon Alexa smart home devices directly from
Home Assistant OS. This is **not** a Home Assistant integration – it is a
standalone app that runs its own web server and is accessible via the HA sidebar.

## Why?

Amazon removed the web interface that allowed bulk management of Alexa devices.
The Alexa App only lets you manage one device at a time which is tedious.
This app provides a web-based alternative for viewing, renaming, deleting, and
bulk-managing your Alexa devices.

## Setup

No add-on configuration options are required. Authentication works via an
Amazon web login directly in the browser:

1. Start the add-on and open **Alexa Devices** from the Home Assistant sidebar.
2. Click **🔑 Alexa verbinden** and sign in with your Amazon account
   (the same account your Alexa devices are registered to).
3. After a successful login the app stores the Alexa web session locally in
   the add-on (`/data/alexa_session.json`) and loads your device list.

No Amazon Developer Console, OAuth client, or API keys are needed.

## Using the Web UI

The device table shows Echo devices (🔵) and smart home devices (🏠) together.

- **Filter**: every column has a filter field or dropdown in the second header
  row. The counter shows how many devices match.
- **Sort**: click a column header to sort ascending/descending.
- **Rename**: click the ✏️ button in a row and enter the new name.
  Skill-managed devices that cannot be renamed via the Alexa API report a
  clear error – rename those in their source system (e.g. openHAB,
  Home Assistant) instead.
- **Delete**: select devices via the checkboxes and click
  **🗑 Auswahl löschen**. A confirmation dialog lists all affected devices.
- **CSV export**: **⬇ CSV** downloads the currently filtered list as a
  semicolon-separated CSV file.
- **Debug**: the **🛠 Debug** button opens a console that calls the app's API
  endpoints and pretty-prints the JSON responses – useful for diagnostics.

## Logging out

**⏏ Abmelden** deletes the stored Alexa web session from the add-on.
